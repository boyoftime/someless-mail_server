import re


def theme_of(html):
    return re.search(r'<html lang="en" data-theme="(\w+)">', html).group(1)


def test_first_visit_is_dark(client):
    for path in ["/", "/login"]:
        html = client.get(path).get_data(as_text=True)

        assert theme_of(html) == "dark"
        assert '<meta name="color-scheme" content="dark">' in html


def test_picked_theme_applies_to_every_page_even_after_logging_out(client, login):
    client.set_cookie("theme", "light")
    pages = [client.get("/").get_data(as_text=True)]
    login()
    pages.append(client.get("/dashboard").get_data(as_text=True))
    pages.append(client.get("/settings").get_data(as_text=True))
    logged_out = client.post("/logout", follow_redirects=True)
    pages.append(logged_out.get_data(as_text=True))

    assert "Log in" in pages[-1]  # the login page, after logging out
    for html in pages:
        assert theme_of(html) == "light"
        assert '<meta name="color-scheme" content="light">' in html


def test_unknown_theme_falls_back_to_dark(client):
    client.set_cookie("theme", "purple")

    assert theme_of(client.get("/login").get_data(as_text=True)) == "dark"


def test_theme_switch_sits_with_the_account_options(client, login):
    login()
    html = client.get("/dashboard").get_data(as_text=True)
    panel = html[html.index('id="account-panel"'):html.index("</dialog>")]
    switch = re.search(r'<button [^>]*data-theme-switch[^>]*>', panel)

    assert switch
    assert 'role="switch"' in switch.group(0)
    assert 'aria-checked="true"' in switch.group(0)  # dark is on
    assert 'src="/static/js/theme.js?v=' in html


def test_switch_shows_light_as_off(client, login):
    client.set_cookie("theme", "light")
    login()
    html = client.get("/dashboard").get_data(as_text=True)

    assert re.search(r'<button [^>]*data-theme-switch[^>]*aria-checked="false"', html)


def test_colours_follow_the_picked_theme_not_the_device(client):
    css = client.get("/static/css/style.css").get_data(as_text=True)
    lottie = client.get("/static/js/lottie-autoplay.js").get_data(as_text=True)

    assert "prefers-color-scheme" not in css
    assert "prefers-color-scheme" not in lottie
