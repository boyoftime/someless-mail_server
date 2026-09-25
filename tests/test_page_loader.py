def dashboard(client, login):
    login()
    return client.get("/dashboard").get_data(as_text=True)


def test_signed_in_pages_show_a_loader_while_the_next_page_loads(client, login):
    html = dashboard(client, login)

    assert '<div class="page-loader" id="page-loader"' in html
    assert 'data-loader-animation="/static/lottie/page-loader.json?v=' in html
    assert 'src="/static/js/page-loader.js?v=' in html
    assert "layers" in client.get("/static/lottie/page-loader.json").get_json()


def test_login_page_has_no_page_loader(client):
    assert "page-loader" not in client.get("/login").get_data(as_text=True)


def test_moving_between_pages_swaps_only_the_main_area(client, login):
    html = dashboard(client, login)

    # page-swap.js replaces just <main id="app-main">; the menu and the loader stay outside it
    main_start = html.index('<main class="app-main" id="app-main">')
    main_end = html.index("</main>")
    assert 'src="/static/js/page-swap.js?v=' in html
    assert html.index('id="side-menu"') < main_start
    assert not (main_start < html.index('id="page-loader"') < main_end)


def test_the_admins_name_outside_the_main_area_is_refreshed_too(client, login):
    html = dashboard(client, login)

    # swapped along with the main area, so a new username shows everywhere at once
    assert 'id="topbar-user" data-swap-refresh' in html
    assert 'id="signed-in-as" data-swap-refresh' in html
