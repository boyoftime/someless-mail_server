import html


def main_area(client, login):
    login()
    page = html.unescape(client.get("/dashboard").get_data(as_text=True))
    return page[page.index('<main class="app-main"'):page.index("</main>")]


def test_dashboard_says_coming_soon(client, login):
    main = main_area(client, login)

    assert '<h1 class="page-title">Dashboard</h1>' in main
    assert "Coming soon" in main
    assert "Signed in as" not in main  # the old facts are gone (the menu shows who is signed in)


def test_dashboard_still_warns_about_the_default_password(client, login):
    assert "You're still using the default password" in main_area(client, login)
