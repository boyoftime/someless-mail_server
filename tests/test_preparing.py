"""The first start: while the mail engine is set up, the welcome and login pages say so, and
move on by themselves once it's ready (preparing.js)."""
import re

from someless import engine as engine_module


def first_start(app, step="new"):
    app.config["ENGINE_ENABLED"] = True
    with app.app_context():
        engine_module.remember(setup_step=step)


def test_the_first_start_shows_the_preparing_screen(app, client):
    first_start(app)

    page = client.get("/").get_data(as_text=True)

    assert "Preparing your Someless Mail server" in page
    assert 'data-progress="/preparing/progress"' in page and 'data-next="/"' in page
    assert "lottie/contact-mail.json" in page


def test_the_login_page_waits_too(app, client):
    first_start(app)

    page = client.get("/login").get_data(as_text=True)

    assert "Preparing your Someless Mail server" in page and 'data-next="/login"' in page


def test_the_steps_show_how_far_it_got(app, client):
    first_start(app, "bootstrapped")

    page = client.get("/").get_data(as_text=True)

    steps = re.findall(r'<li class="preparing-step (is-\w+)"[^>]*>.*?<span class="preparing-step-text">([^<]+)', page, re.S)
    assert steps == [("is-done", "Setting up the mail engine"), ("is-active", "Getting it ready to send"),
                     ("is-waiting", "Almost there")]


def test_once_ready_the_pages_are_as_ever(app, client):
    first_start(app, "ready")

    assert "Preparing" not in client.get("/").get_data(as_text=True)
    assert "Preparing" not in client.get("/login").get_data(as_text=True)


def test_without_a_mail_engine_there_is_nothing_to_prepare(app, client):
    with app.app_context():
        engine_module.remember(setup_step="new")

    assert "Preparing" not in client.get("/").get_data(as_text=True)


def test_the_progress_follows_the_setup(app, client):
    first_start(app)
    assert client.get("/preparing/progress").get_json() == {"step": "new", "ready": False}

    first_start(app, "provisioned")
    assert client.get("/preparing/progress").get_json() == {"step": "provisioned", "ready": False}

    first_start(app, "ready")
    assert client.get("/preparing/progress").get_json() == {"step": "ready", "ready": True}


def test_continue_goes_on_without_waiting(app, client):
    """If setting up takes too long, Continue lets the admin in; the checklist says the rest."""
    first_start(app)

    response = client.get("/preparing/skip?next=/login")

    assert response.headers["Location"] == "/login"
    assert "Preparing" not in client.get("/login").get_data(as_text=True)


def test_continue_only_goes_to_the_panels_own_pages(app, client):
    first_start(app)

    for elsewhere in ("https://evil.example/", "//evil.example/", r"/\evil.example"):
        assert client.get("/preparing/skip", query_string={"next": elsewhere}).headers["Location"] == "/"
