"""FastAPI application factory.

Composes the web/API layer over the bell controller and scheduler. The app is
created with explicit dependencies so tests can inject a mock-hardware controller
and an in-memory database (see tests/conftest.py).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from starlette.middleware.sessions import SessionMiddleware

from .. import __version__, auth, updater
from ..bell import BellController
from ..config import Settings
from ..db import get_setting, session_scope, set_setting
from ..models import (
    BellEvent,
    CalendarRule,
    CalendarRuleKind,
    DayType,
    RingLog,
    RingSource,
    Sound,
    WeekdayDefault,
)
from ..monitor import HealthMonitor
from ..notify import Notifier
from ..schedule_service import planned_rings_for, resolution_for
from ..scheduler import BellScheduler

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def require_login(request: Request) -> str:
    """Auth dependency. Defined at module scope so FastAPI can resolve the
    ``LoggedIn`` alias under ``from __future__ import annotations``."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Login required")
    return str(user)


LoggedIn = Annotated[str, Depends(require_login)]


def create_app(
    controller: BellController,
    scheduler: BellScheduler,
    settings: Settings,
    monitor: HealthMonitor | None = None,
) -> FastAPI:
    app = FastAPI(title="ViejoolBel", version=__version__)
    app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, max_age=7 * 24 * 3600)
    app.state.controller = controller
    app.state.scheduler = scheduler
    app.state.settings = settings
    app.state.monitor = monitor

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # --- auth routes -----------------------------------------------------
    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "login.html", {"error": None})

    @app.post("/login", response_model=None)
    def login(
        request: Request,
        username: Annotated[str, Form()],
        password: Annotated[str, Form()],
    ) -> RedirectResponse | HTMLResponse:
        with session_scope() as s:
            ok = auth.verify(s, username, password)
        if not ok:
            return templates.TemplateResponse(
                request, "login.html", {"error": "Invalid credentials"}, status_code=401
            )
        request.session["user"] = username
        return RedirectResponse("/", status_code=303)

    @app.post("/logout")
    def logout(request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    # --- dashboard -------------------------------------------------------
    @app.get("/", response_class=HTMLResponse, response_model=None)
    def dashboard(request: Request) -> HTMLResponse | RedirectResponse:
        if not request.session.get("user"):
            return RedirectResponse("/login", status_code=303)
        now = scheduler.now()
        with session_scope() as s:
            resolution = resolution_for(s, now.date())
            plan = planned_rings_for(s, now.date())
            sounds = list(s.scalars(select(Sound)))
            recent = list(
                s.scalars(select(RingLog).order_by(RingLog.ts.desc()).limit(10))
            )
            silenced = get_setting(s, "silence_date", "") == now.date().isoformat()
            default_pw = auth.uses_default_password(s)
            webhook_url = get_setting(s, "notify_webhook_url", settings.notify_webhook_url)
            heartbeat_url = get_setting(s, "heartbeat_url", settings.heartbeat_url)
        report = monitor.evaluate_once() if monitor is not None else None
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "version": __version__,
                "now": now,
                "resolution": resolution,
                "plan": plan,
                "next_ring": scheduler.next_ring(),
                "sounds": sounds,
                "recent": recent,
                "silenced": silenced,
                "default_pw": default_pw,
                "is_ringing": controller.is_ringing,
                "health": report,
                "webhook_url": webhook_url,
                "heartbeat_url": heartbeat_url,
            },
        )

    # --- management pages ------------------------------------------------
    def _guard(request: Request) -> RedirectResponse | None:
        return None if request.session.get("user") else RedirectResponse("/login", status_code=303)

    def _page(request: Request, template: str, active: str, **ctx: object) -> HTMLResponse:
        base: dict[str, object] = {"version": __version__, "active": active}
        base.update(ctx)
        return templates.TemplateResponse(request, template, base)

    @app.get("/roosters", response_class=HTMLResponse, response_model=None)
    def roosters_page(request: Request) -> HTMLResponse | RedirectResponse:
        if (redir := _guard(request)) is not None:
            return redir
        weekday_names = ["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag",
                         "Zaterdag", "Zondag"]
        with session_scope() as s:
            day_types = [
                {"id": d.id, "name": d.name, "is_default": d.is_default, "count": len(d.events)}
                for d in s.scalars(select(DayType))
            ]
            names = {d["id"]: d["name"] for d in day_types}
            wd_rows = {wd.weekday: wd for wd in s.scalars(select(WeekdayDefault))}
            weekdays = []
            for i in range(7):
                wd = wd_rows.get(i)
                wd_dtid = wd.day_type_id if wd else None
                weekdays.append(
                    {
                        "index": i,
                        "name": weekday_names[i],
                        "closed": wd is None or wd.kind is CalendarRuleKind.CLOSED,
                        "day_type_id": wd_dtid,
                        "day_type_name": names.get(wd_dtid) if wd_dtid is not None else None,
                    }
                )
        return _page(
            request, "roosters.html", "roosters", day_types=day_types, weekdays=weekdays
        )

    @app.get("/roosters/{day_type_id}", response_class=HTMLResponse, response_model=None)
    def rooster_detail_page(
        request: Request, day_type_id: int
    ) -> HTMLResponse | RedirectResponse:
        if (redir := _guard(request)) is not None:
            return redir
        with session_scope() as s:
            dt_ = s.get(DayType, day_type_id)
            if dt_ is None:
                raise HTTPException(404, "No such day-type")
            sound_names = {snd.id: snd.name for snd in s.scalars(select(Sound))}

            def _sname(sid: int | None) -> str:
                return sound_names.get(sid, "—") if sid is not None else "—"

            day_type = {"id": dt_.id, "name": dt_.name, "is_default": dt_.is_default}
            events = [
                {
                    "id": e.id,
                    "at": e.at.strftime("%H:%M"),
                    "sound_id": e.sound_id,
                    "sound_name": _sname(e.sound_id),
                    "duration": e.duration,
                    "use_audio": e.use_audio,
                    "use_relay": e.use_relay,
                    "label": e.label,
                }
                for e in dt_.events
            ]
            sounds = [{"id": sid, "name": n} for sid, n in sound_names.items()]
        return _page(
            request,
            "rooster_detail.html",
            "roosters",
            day_type=day_type,
            events=events,
            sounds=sounds,
        )

    @app.get("/kalender", response_class=HTMLResponse, response_model=None)
    def kalender_page(
        request: Request, year: int | None = None, month: int | None = None
    ) -> HTMLResponse | RedirectResponse:
        if (redir := _guard(request)) is not None:
            return redir
        import calendar as _cal

        today = scheduler.now().date()
        y = year or today.year
        m = month or today.month
        first_weekday, days_in_month = _cal.monthrange(y, m)
        with session_scope() as s:
            names = {d.id: d.name for d in s.scalars(select(DayType))}
            counts = {d.id: len(d.events) for d in s.scalars(select(DayType))}
            cells = []
            for day in range(1, days_in_month + 1):
                date = dt.date(y, m, day)
                res = resolution_for(s, date)
                cells.append(
                    {
                        "day": day,
                        "date": date.isoformat(),
                        "closed": res.closed,
                        "is_today": date == today,
                        "day_type_name": (
                            names.get(res.day_type_id) if res.day_type_id is not None else None
                        ),
                        "reason": res.reason,
                        "ring_count": (
                            counts.get(res.day_type_id, 0)
                            if (not res.closed and res.day_type_id is not None)
                            else 0
                        ),
                    }
                )
            rules = [
                {
                    "id": r.id,
                    "start_date": r.start_date.isoformat(),
                    "end_date": r.end_date.isoformat(),
                    "kind": r.kind.value,
                    "day_type_name": names.get(r.day_type_id) if r.day_type_id else None,
                    "note": r.note,
                }
                for r in s.scalars(select(CalendarRule).order_by(CalendarRule.start_date))
            ]
            day_types = [{"id": i, "name": n} for i, n in names.items()]
        prev_m = (m - 2) % 12 + 1
        prev_y = y - 1 if m == 1 else y
        next_m = m % 12 + 1
        next_y = y + 1 if m == 12 else y
        month_names = ["", "januari", "februari", "maart", "april", "mei", "juni", "juli",
                       "augustus", "september", "oktober", "november", "december"]
        return _page(
            request,
            "kalender.html",
            "kalender",
            year=y,
            month=m,
            month_name=month_names[m],
            first_weekday=first_weekday,
            cells=cells,
            rules=rules,
            day_types=day_types,
            prev_y=prev_y,
            prev_m=prev_m,
            next_y=next_y,
            next_m=next_m,
        )

    @app.get("/geluiden", response_class=HTMLResponse, response_model=None)
    def geluiden_page(request: Request) -> HTMLResponse | RedirectResponse:
        if (redir := _guard(request)) is not None:
            return redir
        with session_scope() as s:
            sounds = [
                {
                    "id": snd.id,
                    "name": snd.name,
                    "default_duration": snd.default_duration,
                    "is_alarm": snd.is_alarm,
                    "in_use": s.scalar(select(BellEvent).where(BellEvent.sound_id == snd.id))
                    is not None,
                }
                for snd in s.scalars(select(Sound))
            ]
        return _page(request, "geluiden.html", "geluiden", sounds=sounds)

    @app.get("/instellingen", response_class=HTMLResponse, response_model=None)
    def instellingen_page(request: Request) -> HTMLResponse | RedirectResponse:
        if (redir := _guard(request)) is not None:
            return redir
        with session_scope() as s:
            webhook_url = get_setting(s, "notify_webhook_url", settings.notify_webhook_url)
            heartbeat_url = get_setting(s, "heartbeat_url", settings.heartbeat_url)
            volume_db = int(get_setting(s, "volume_db", "0") or "0")
            default_pw = auth.uses_default_password(s)
        return _page(
            request,
            "instellingen.html",
            "instellingen",
            webhook_url=webhook_url,
            heartbeat_url=heartbeat_url,
            volume_db=volume_db,
            timezone=settings.timezone,
            default_pw=default_pw,
        )

    # --- status API ------------------------------------------------------
    @app.get("/api/status")
    def status(_: LoggedIn) -> JSONResponse:
        now = scheduler.now()
        with session_scope() as s:
            resolution = resolution_for(s, now.date())
            plan = planned_rings_for(s, now.date())
        nxt = scheduler.next_ring()
        return JSONResponse(
            {
                "version": __version__,
                "time": now.isoformat(),
                "timezone": settings.timezone,
                "closed": resolution.closed,
                "reason": resolution.reason,
                "ring_count_today": len(plan),
                "next_ring": nxt.isoformat() if nxt else None,
                "is_ringing": controller.is_ringing,
            }
        )

    # --- health & alerting ----------------------------------------------
    @app.get("/api/health")
    def health(_: LoggedIn) -> JSONResponse:
        if monitor is None:
            return JSONResponse({"level": "unknown", "checks": []})
        report = monitor.evaluate_once()
        return JSONResponse(report.as_dict())

    @app.get("/api/notify-settings")
    def get_notify_settings(_: LoggedIn) -> JSONResponse:
        with session_scope() as s:
            return JSONResponse(
                {
                    "notify_webhook_url": get_setting(
                        s, "notify_webhook_url", settings.notify_webhook_url
                    ),
                    "heartbeat_url": get_setting(s, "heartbeat_url", settings.heartbeat_url),
                }
            )

    @app.post("/api/notify-settings")
    def set_notify_settings(
        _: LoggedIn,
        notify_webhook_url: Annotated[str, Form()] = "",
        heartbeat_url: Annotated[str, Form()] = "",
    ) -> JSONResponse:
        with session_scope() as s:
            set_setting(s, "notify_webhook_url", notify_webhook_url.strip())
            set_setting(s, "heartbeat_url", heartbeat_url.strip())
        return JSONResponse({"ok": True})

    @app.post("/api/notify-test")
    def notify_test(_: LoggedIn) -> JSONResponse:
        with session_scope() as s:
            url = get_setting(s, "notify_webhook_url", settings.notify_webhook_url)
        if not url:
            raise HTTPException(400, "No webhook URL configured")
        ok = Notifier().alert(
            url,
            level="ok",
            title="ViejoolBel testmelding",
            message="Dit is een testmelding vanuit ViejoolBel.",
        )
        return JSONResponse({"ok": ok}, status_code=200 if ok else 502)

    # --- manual control --------------------------------------------------
    @app.post("/api/ring-now")
    def ring_now(
        _: LoggedIn,
        sound_id: Annotated[int | None, Form()] = None,
        duration: Annotated[int, Form()] = 8,
        use_audio: Annotated[bool, Form()] = True,
        use_relay: Annotated[bool, Form()] = True,
    ) -> JSONResponse:
        ok = controller.ring(
            source=RingSource.MANUAL,
            sound_id=sound_id,
            duration=duration,
            use_audio=use_audio,
            use_relay=use_relay,
        )
        return JSONResponse({"ok": ok}, status_code=200 if ok else 409)

    @app.post("/api/self-test")
    def self_test(_: LoggedIn) -> JSONResponse:
        controller.self_test()
        return JSONResponse({"ok": True})

    @app.post("/api/silence-today")
    def silence_today(_: LoggedIn, on: Annotated[bool, Form()] = True) -> JSONResponse:
        today = scheduler.now().date().isoformat()
        with session_scope() as s:
            set_setting(s, "silence_date", today if on else "")
        scheduler.reload()
        return JSONResponse({"ok": True, "silenced": on})

    # --- sounds ----------------------------------------------------------
    @app.get("/api/sounds")
    def list_sounds(_: LoggedIn) -> JSONResponse:
        with session_scope() as s:
            return JSONResponse(
                [
                    {
                        "id": snd.id,
                        "name": snd.name,
                        "default_duration": snd.default_duration,
                        "is_alarm": snd.is_alarm,
                    }
                    for snd in s.scalars(select(Sound))
                ]
            )

    @app.post("/api/sounds")
    async def upload_sound(
        _: LoggedIn,
        name: Annotated[str, Form()],
        file: UploadFile,
        is_alarm: Annotated[bool, Form()] = False,
    ) -> JSONResponse:
        allowed = {".mp3", ".wav", ".ogg"}
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in allowed:
            raise HTTPException(400, f"Unsupported file type {suffix!r}")
        settings.sounds_dir.mkdir(parents=True, exist_ok=True)
        safe = f"{abs(hash(name)) % 10_000_000}{suffix}"
        dest = settings.sounds_dir / safe
        dest.write_bytes(await file.read())
        with session_scope() as s:
            if s.scalar(select(Sound).where(Sound.name == name)):
                raise HTTPException(409, "A sound with that name already exists")
            snd = Sound(name=name, filename=safe, is_alarm=is_alarm)
            s.add(snd)
            s.flush()
            new_id = snd.id
        return JSONResponse({"id": new_id, "name": name}, status_code=201)

    @app.delete("/api/sounds/{sound_id}")
    def delete_sound(_: LoggedIn, sound_id: int) -> JSONResponse:
        with session_scope() as s:
            snd = s.get(Sound, sound_id)
            if snd is None:
                raise HTTPException(404, "No such sound")
            in_use = s.scalar(select(BellEvent).where(BellEvent.sound_id == sound_id))
            if in_use is not None:
                raise HTTPException(409, "Sound is still used by one or more bell events")
            (settings.sounds_dir / snd.filename).unlink(missing_ok=True)
            s.delete(snd)
        return JSONResponse({"ok": True})

    @app.get("/api/sounds/{sound_id}/audio")
    def sound_audio(_: LoggedIn, sound_id: int) -> FileResponse:
        with session_scope() as s:
            snd = s.get(Sound, sound_id)
            if snd is None:
                raise HTTPException(404, "No such sound")
            path = settings.sounds_dir / snd.filename
        if not path.exists():
            raise HTTPException(404, "Sound file missing on disk")
        return FileResponse(path)

    # --- day-types & events (schedule) ----------------------------------
    @app.get("/api/day-types")
    def list_day_types(_: LoggedIn) -> JSONResponse:
        with session_scope() as s:
            return JSONResponse(
                [
                    {
                        "id": dt_.id,
                        "name": dt_.name,
                        "is_default": dt_.is_default,
                        "events": [
                            {
                                "id": e.id,
                                "at": e.at.strftime("%H:%M"),
                                "sound_id": e.sound_id,
                                "duration": e.duration,
                                "use_audio": e.use_audio,
                                "use_relay": e.use_relay,
                                "label": e.label,
                            }
                            for e in dt_.events
                        ],
                    }
                    for dt_ in s.scalars(select(DayType))
                ]
            )

    @app.post("/api/day-types")
    def create_day_type(_: LoggedIn, name: Annotated[str, Form()]) -> JSONResponse:
        name = name.strip()
        if not name:
            raise HTTPException(400, "Name is required")
        with session_scope() as s:
            if s.scalar(select(DayType).where(DayType.name == name)):
                raise HTTPException(409, "Day-type name already exists")
            dt_ = DayType(name=name)
            s.add(dt_)
            s.flush()
            new_id = dt_.id
        return JSONResponse({"id": new_id, "name": name}, status_code=201)

    @app.post("/api/day-types/{day_type_id}/rename")
    def rename_day_type(
        _: LoggedIn, day_type_id: int, name: Annotated[str, Form()]
    ) -> JSONResponse:
        name = name.strip()
        if not name:
            raise HTTPException(400, "Name is required")
        with session_scope() as s:
            dt_ = s.get(DayType, day_type_id)
            if dt_ is None:
                raise HTTPException(404, "No such day-type")
            clash = s.scalar(select(DayType).where(DayType.name == name, DayType.id != day_type_id))
            if clash is not None:
                raise HTTPException(409, "Day-type name already exists")
            dt_.name = name
        return JSONResponse({"ok": True})

    @app.post("/api/day-types/{day_type_id}/default")
    def set_default_day_type(_: LoggedIn, day_type_id: int) -> JSONResponse:
        with session_scope() as s:
            dt_ = s.get(DayType, day_type_id)
            if dt_ is None:
                raise HTTPException(404, "No such day-type")
            for other in s.scalars(select(DayType)):
                other.is_default = other.id == day_type_id
        scheduler.reload()
        return JSONResponse({"ok": True})

    @app.delete("/api/day-types/{day_type_id}")
    def delete_day_type(_: LoggedIn, day_type_id: int) -> JSONResponse:
        with session_scope() as s:
            dt_ = s.get(DayType, day_type_id)
            if dt_ is None:
                raise HTTPException(404, "No such day-type")
            if dt_.is_default:
                raise HTTPException(409, "Cannot delete the default day-type; set another first")
            # Clean up references: weekday defaults fall back to closed, and
            # calendar rules that pointed at this day-type are removed.
            for wd in s.scalars(
                select(WeekdayDefault).where(WeekdayDefault.day_type_id == day_type_id)
            ):
                wd.kind = CalendarRuleKind.CLOSED
                wd.day_type_id = None
            for rule in s.scalars(
                select(CalendarRule).where(CalendarRule.day_type_id == day_type_id)
            ):
                s.delete(rule)
            s.delete(dt_)
        scheduler.reload()
        return JSONResponse({"ok": True})

    @app.post("/api/day-types/{day_type_id}/events")
    def add_event(
        _: LoggedIn,
        day_type_id: int,
        at: Annotated[str, Form()],
        sound_id: Annotated[int | None, Form()] = None,
        duration: Annotated[int, Form()] = 8,
        use_audio: Annotated[bool, Form()] = True,
        use_relay: Annotated[bool, Form()] = True,
        label: Annotated[str, Form()] = "",
    ) -> JSONResponse:
        parsed = _parse_time(at)
        with session_scope() as s:
            if s.get(DayType, day_type_id) is None:
                raise HTTPException(404, "No such day-type")
            if sound_id is not None and s.get(Sound, sound_id) is None:
                raise HTTPException(400, "No such sound")
            e = BellEvent(
                day_type_id=day_type_id,
                at=parsed,
                sound_id=sound_id,
                duration=duration,
                use_audio=use_audio,
                use_relay=use_relay,
                label=label,
            )
            s.add(e)
            s.flush()
            new_id = e.id
        scheduler.reload()
        return JSONResponse({"id": new_id}, status_code=201)

    @app.post("/api/events/{event_id}")
    def edit_event(
        _: LoggedIn,
        event_id: int,
        at: Annotated[str, Form()],
        sound_id: Annotated[int | None, Form()] = None,
        duration: Annotated[int, Form()] = 8,
        use_audio: Annotated[bool, Form()] = True,
        use_relay: Annotated[bool, Form()] = True,
        label: Annotated[str, Form()] = "",
    ) -> JSONResponse:
        parsed = _parse_time(at)
        with session_scope() as s:
            e = s.get(BellEvent, event_id)
            if e is None:
                raise HTTPException(404, "No such event")
            if sound_id is not None and s.get(Sound, sound_id) is None:
                raise HTTPException(400, "No such sound")
            e.at = parsed
            e.sound_id = sound_id
            e.duration = duration
            e.use_audio = use_audio
            e.use_relay = use_relay
            e.label = label
        scheduler.reload()
        return JSONResponse({"ok": True})

    @app.delete("/api/events/{event_id}")
    def delete_event(_: LoggedIn, event_id: int) -> JSONResponse:
        with session_scope() as s:
            e = s.get(BellEvent, event_id)
            if e is None:
                raise HTTPException(404, "No such event")
            s.delete(e)
        scheduler.reload()
        return JSONResponse({"ok": True})

    # --- weekday defaults ------------------------------------------------
    @app.get("/api/weekday-defaults")
    def list_weekday_defaults(_: LoggedIn) -> JSONResponse:
        with session_scope() as s:
            rows = {wd.weekday: wd for wd in s.scalars(select(WeekdayDefault))}
            return JSONResponse(
                [
                    {
                        "weekday": i,
                        "kind": rows[i].kind.value if i in rows else "closed",
                        "day_type_id": rows[i].day_type_id if i in rows else None,
                    }
                    for i in range(7)
                ]
            )

    @app.post("/api/weekday-defaults")
    def set_weekday_default(
        _: LoggedIn,
        weekday: Annotated[int, Form()],
        kind: Annotated[str, Form()],
        day_type_id: Annotated[int | None, Form()] = None,
    ) -> JSONResponse:
        if not 0 <= weekday <= 6:
            raise HTTPException(400, "weekday must be 0..6")
        try:
            rule_kind = CalendarRuleKind(kind)
        except ValueError as exc:
            raise HTTPException(400, "Invalid kind") from exc
        if rule_kind is CalendarRuleKind.DAY_TYPE and day_type_id is None:
            raise HTTPException(400, "day_type_id required for kind=day_type")
        with session_scope() as s:
            if day_type_id is not None and s.get(DayType, day_type_id) is None:
                raise HTTPException(400, "No such day-type")
            row = s.get(WeekdayDefault, weekday)
            if row is None:
                row = WeekdayDefault(weekday=weekday)
                s.add(row)
            row.kind = rule_kind
            row.day_type_id = day_type_id if rule_kind is CalendarRuleKind.DAY_TYPE else None
        scheduler.reload()
        return JSONResponse({"ok": True})

    # --- calendar --------------------------------------------------------
    @app.get("/api/calendar")
    def list_calendar(_: LoggedIn) -> JSONResponse:
        with session_scope() as s:
            return JSONResponse(
                [
                    {
                        "id": r.id,
                        "start_date": r.start_date.isoformat(),
                        "end_date": r.end_date.isoformat(),
                        "kind": r.kind.value,
                        "day_type_id": r.day_type_id,
                        "note": r.note,
                    }
                    for r in s.scalars(
                        select(CalendarRule).order_by(CalendarRule.start_date)
                    )
                ]
            )

    @app.delete("/api/calendar/{rule_id}")
    def delete_calendar_rule(_: LoggedIn, rule_id: int) -> JSONResponse:
        with session_scope() as s:
            r = s.get(CalendarRule, rule_id)
            if r is None:
                raise HTTPException(404, "No such rule")
            s.delete(r)
        scheduler.reload()
        return JSONResponse({"ok": True})

    @app.get("/api/calendar/month")
    def calendar_month(
        _: LoggedIn,
        year: int,
        month: int,
    ) -> JSONResponse:
        if not 1 <= month <= 12:
            raise HTTPException(400, "month must be 1..12")
        import calendar as _cal

        days_in_month = _cal.monthrange(year, month)[1]
        out = []
        with session_scope() as s:
            names = {d.id: d.name for d in s.scalars(select(DayType))}
            counts = {
                d.id: len(d.events) for d in s.scalars(select(DayType))
            }
            for day in range(1, days_in_month + 1):
                date = dt.date(year, month, day)
                res = resolution_for(s, date)
                out.append(
                    {
                        "date": date.isoformat(),
                        "weekday": date.weekday(),
                        "closed": res.closed,
                        "day_type_id": res.day_type_id,
                        "day_type_name": (
                            names.get(res.day_type_id) if res.day_type_id is not None else None
                        ),
                        "reason": res.reason,
                        "ring_count": (
                            counts.get(res.day_type_id, 0)
                            if (not res.closed and res.day_type_id is not None)
                            else 0
                        ),
                    }
                )
        return JSONResponse({"year": year, "month": month, "days": out})

    @app.post("/api/calendar")
    def add_calendar_rule(
        _: LoggedIn,
        start_date: Annotated[str, Form()],
        end_date: Annotated[str, Form()],
        kind: Annotated[str, Form()],
        day_type_id: Annotated[int | None, Form()] = None,
        note: Annotated[str, Form()] = "",
    ) -> JSONResponse:
        try:
            start = dt.date.fromisoformat(start_date)
            end = dt.date.fromisoformat(end_date)
        except ValueError as exc:
            raise HTTPException(400, "Invalid date") from exc
        if end < start:
            raise HTTPException(400, "end_date before start_date")
        try:
            rule_kind = CalendarRuleKind(kind)
        except ValueError as exc:
            raise HTTPException(400, "Invalid kind") from exc
        if rule_kind is CalendarRuleKind.DAY_TYPE and day_type_id is None:
            raise HTTPException(400, "day_type_id required for kind=day_type")
        with session_scope() as s:
            rule = CalendarRule(
                start_date=start,
                end_date=end,
                kind=rule_kind,
                day_type_id=day_type_id,
                note=note,
            )
            s.add(rule)
            s.flush()
            new_id = rule.id
        scheduler.reload()
        return JSONResponse({"id": new_id}, status_code=201)

    # --- settings & security --------------------------------------------
    @app.post("/api/password")
    def change_password(_: LoggedIn, new_password: Annotated[str, Form()]) -> JSONResponse:
        try:
            with session_scope() as s:
                auth.set_password(s, new_password)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return JSONResponse({"ok": True})

    @app.get("/api/settings")
    def get_settings(_: LoggedIn) -> JSONResponse:
        with session_scope() as s:
            return JSONResponse(
                {
                    "timezone": settings.timezone,
                    "volume_db": int(get_setting(s, "volume_db", "0") or "0"),
                }
            )

    @app.post("/api/settings")
    def update_settings(_: LoggedIn, volume_db: Annotated[int, Form()] = 0) -> JSONResponse:
        if not -40 <= volume_db <= 20:
            raise HTTPException(400, "volume_db out of range (-40..20)")
        with session_scope() as s:
            set_setting(s, "volume_db", str(volume_db))
        return JSONResponse({"ok": True})

    # --- software update -------------------------------------------------
    @app.get("/api/update/check")
    def update_check(_: LoggedIn) -> JSONResponse:
        current = updater.current_version()
        info = updater.check_latest(settings.update_repo, token=settings.github_token or None)
        if info is None:
            return JSONResponse(
                {
                    "available": False,
                    "current": current,
                    "latest": None,
                    "error": "Kon de updateserver niet bereiken (geen internet of geen release).",
                }
            )
        return JSONResponse(
            {
                "available": updater.is_newer(info.tag),
                "current": current,
                "latest": info.tag,
                "notes": info.notes,
                "url": info.url,
            }
        )

    @app.post("/api/update/apply")
    def update_apply(_: LoggedIn, tag: Annotated[str, Form()]) -> JSONResponse:
        if not updater.is_valid_tag(tag):
            raise HTTPException(400, f"Ongeldige versietag: {tag!r}")
        started, message = updater.launch_update(tag, settings.update_script)
        return JSONResponse({"ok": started, "detail": message}, status_code=202 if started else 409)

    # --- backup / restore -----------------------------------------------
    @app.get("/api/backup")
    def backup(_: LoggedIn) -> JSONResponse:
        with session_scope() as s:
            data = {
                "version": __version__,
                "day_types": [
                    {
                        "name": dt_.name,
                        "is_default": dt_.is_default,
                        "events": [
                            {
                                "at": e.at.strftime("%H:%M"),
                                "duration": e.duration,
                                "use_audio": e.use_audio,
                                "use_relay": e.use_relay,
                                "label": e.label,
                            }
                            for e in dt_.events
                        ],
                    }
                    for dt_ in s.scalars(select(DayType))
                ],
            }
        return JSONResponse(data)

    return app


def _parse_time(value: str) -> dt.time:
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return dt.datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    raise HTTPException(400, f"Invalid time {value!r}; expected HH:MM")
