"""The system ships with a default collection of bell sounds (installed on first
run) so it can ring out of the box without any uploads."""

from __future__ import annotations

from sqlalchemy import select

from viejoolbel.db import DEFAULT_SOUNDS, install_default_sounds, session_scope
from viejoolbel.models import Sound


def test_default_sounds_installed_on_first_run(initialized_db, settings):
    with session_scope() as s:
        count = install_default_sounds(s, settings.sounds_dir)
    assert count == len(DEFAULT_SOUNDS)
    with session_scope() as s:
        names = {snd.name for snd in s.scalars(select(Sound))}
    assert {"Enkele bel", "Schoolbel"} <= names
    # Files were actually copied to disk so they can be played/served.
    for _name, filename, _dur, _alarm in DEFAULT_SOUNDS:
        assert (settings.sounds_dir / filename).exists()


def test_install_is_idempotent_and_never_overwrites(initialized_db, settings):
    with session_scope() as s:
        install_default_sounds(s, settings.sounds_dir)
    # Second call is a no-op because sounds already exist.
    with session_scope() as s:
        assert install_default_sounds(s, settings.sounds_dir) == 0


def test_service_installs_defaults(service):
    resp_sounds = service  # the Service fixture ran install during __init__
    with session_scope() as s:
        assert s.scalar(select(Sound).limit(1)) is not None
    assert resp_sounds is not None


def test_bundled_wavs_exist_in_package():
    from viejoolbel.db import _ASSETS_SOUNDS_DIR

    for _name, filename, _dur, _alarm in DEFAULT_SOUNDS:
        assert (_ASSETS_SOUNDS_DIR / filename).exists(), f"missing bundled {filename}"
