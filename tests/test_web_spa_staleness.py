"""The stale-bundle guard in the SPA shell."""

import agentaudit.web.app as web_app


def _touch(path, mtime):
    path.write_text("<html><body><div id='root'></div></body></html>", encoding="utf-8")
    import os

    os.utime(path, (mtime, mtime))


def test_stale_when_source_newer_than_bundle(tmp_path, monkeypatch):
    dist, src = tmp_path / "spa_dist", tmp_path / "spa" / "src"
    dist.mkdir()
    src.mkdir(parents=True)
    _touch(dist / "index.html", 1000)
    _touch(src / "App.tsx", 2000)

    monkeypatch.setattr(web_app, "SPA_DIST", dist)
    monkeypatch.setattr(web_app, "SPA_SRC", src)
    assert web_app._spa_is_stale() is True
    assert "Stale bundle" in web_app._spa_index().body.decode()


def test_fresh_when_bundle_newer(tmp_path, monkeypatch):
    dist, src = tmp_path / "spa_dist", tmp_path / "spa" / "src"
    dist.mkdir()
    src.mkdir(parents=True)
    _touch(src / "App.tsx", 1000)
    _touch(dist / "index.html", 2000)

    monkeypatch.setattr(web_app, "SPA_DIST", dist)
    monkeypatch.setattr(web_app, "SPA_SRC", src)
    assert web_app._spa_is_stale() is False
    assert "Stale bundle" not in web_app._spa_index().body.decode()


def test_missing_source_tree_is_never_stale(tmp_path, monkeypatch):
    """An installed wheel has no spa/src; it must not claim staleness."""
    dist = tmp_path / "spa_dist"
    dist.mkdir()
    _touch(dist / "index.html", 1000)

    monkeypatch.setattr(web_app, "SPA_DIST", dist)
    monkeypatch.setattr(web_app, "SPA_SRC", tmp_path / "nope")
    assert web_app._spa_is_stale() is False
