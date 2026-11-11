"""Link-preview posters: one 1200×630 image per hackathon, drawn on the home server.

``render.publish_posters`` draws the posters whose content changed (see
``hackmash.share``) with headless Chromium and sends them to the site, which
serves them at ``/og/<id>.jpg`` and names them in the page's ``og:image``.
Needs the ``og`` extra: ``uv sync --extra og`` and
``uv run playwright install chromium --only-shell``.
"""
