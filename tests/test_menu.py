import re


def page(client, login, path):
    login()
    return client.get(path).get_data(as_text=True)


def test_hamburger_opens_the_side_menu(client, login):
    html = page(client, login, "/dashboard")

    assert 'data-menu-open aria-controls="side-menu" aria-expanded="false"' in html
    assert '<dialog class="side-menu" id="side-menu"' in html
    assert 'src="/static/js/side-menu.js?v=' in html


def test_hamburger_plays_the_animation_for_the_colour_scheme(client, login):
    html = page(client, login, "/dashboard")

    assert 'data-lottie="/static/lottie/menu-on-dark.json?v=' in html
    assert 'data-lottie-light="/static/lottie/menu-on-light.json?v=' in html
    for name in ["menu-on-dark", "menu-on-light"]:
        assert "layers" in client.get(f"/static/lottie/{name}.json").get_json()


def test_side_menu_links_to_every_page_and_logs_out(client, login):
    html = page(client, login, "/dashboard")
    menu = html[html.index('<dialog class="side-menu"'):html.index("</dialog>")]

    assert 'href="/dashboard"' in menu
    assert 'href="/settings"' in menu
    assert 'action="/logout"' in menu


def test_side_menu_marks_the_page_you_are_on(client, login):
    html = page(client, login, "/settings")
    menu = html[html.index('<dialog class="side-menu"'):html.index("</dialog>")]

    current = re.findall(r'<a [^>]*aria-current="page"[^>]*>', menu)
    assert len(current) == 1
    assert 'href="/settings"' in current[0]


def test_side_menu_is_docked_open_by_default_on_wide_screens(client, login):
    html = page(client, login, "/dashboard")
    head = html[:html.index("</head>")]

    # decided before the page is drawn, so the layout doesn't jump
    assert 'classList.add("menu-docked")' in head
    assert "min-width: 1024px" in head


def side_menu_html(client, login):
    html = page(client, login, "/dashboard")
    return html[html.index('<dialog class="side-menu"'):html.index("</dialog>")]


def test_sidebar_has_its_own_animated_hamburger(client, login):
    menu = side_menu_html(client, login)

    assert 'data-menu-toggle aria-controls="side-menu"' in menu
    assert 'data-lottie="/static/lottie/menu-on-dark.json?v=' in menu
    assert "data-menu-close" not in menu  # the hamburger replaces the close button


def test_collapsed_sidebar_keeps_icons_with_their_names(client, login):
    menu = side_menu_html(client, login)

    # names stay readable (screen readers, hover tooltips) when only icons show
    for name in ["Dashboard", "Settings", "Log out"]:
        assert f'<span class="side-menu-label">{name}</span>' in menu
        assert f'title="{name}"' in menu


def test_every_menu_row_carries_the_active_animation_so_a_click_can_light_it_up(client, login):
    menu = side_menu_html(client, login)  # on the dashboard
    rows = re.findall(r'<a class="side-menu-item".*?</a>', menu, re.S)
    current = [row for row in rows if 'aria-current="page"' in row]

    # Like pineloop: every row has the pulsing hexagon and the stylesheet shows it only on the
    # current row, so a click can make a row current instantly, before its page arrives.
    assert len(rows) >= 2 and len(current) == 1
    for row in rows:
        assert 'class="side-menu-pulse"' in row
        assert 'data-lottie="/static/lottie/menu-active-on-dark.json?v=' in row
        assert 'data-lottie-light="/static/lottie/menu-active-on-light.json?v=' in row
    for name in ["menu-active-on-dark", "menu-active-on-light"]:
        assert "layers" in client.get(f"/static/lottie/{name}.json").get_json()


def test_settings_sits_at_the_bottom_of_the_menu(client, login):
    menu = side_menu_html(client, login)
    main_nav = menu[menu.index('aria-label="Main"'):]
    main_nav = main_nav[:main_nav.index("</nav>")]
    bottom = menu[menu.index('class="side-menu-foot"'):]

    assert 'href="/settings"' not in main_nav
    assert 'href="/settings"' in bottom
    assert bottom.index('href="/settings"') < bottom.index('action="/logout"')  # just above Log out


def account_parts(html):
    foot = html[html.index('class="side-menu-foot"'):]
    sphere = re.search(r'<button class="account-sphere"[^>]*>', foot).group(0)
    panel = re.search(r'<div class="account-panel[^"]*"[^>]*>', foot).group(0)
    return foot, sphere, panel


def test_account_options_hide_behind_the_sphere(client, login):
    foot, sphere, panel = account_parts(page(client, login, "/dashboard"))

    assert 'data-account-toggle aria-controls="account-panel" aria-expanded="false"' in sphere
    assert 'id="account-panel"' in panel and "is-open" not in panel
    assert 'data-lottie="/static/lottie/account-sphere-on-dark.json?v=' in foot
    assert 'data-lottie-light="/static/lottie/account-sphere-on-light.json?v=' in foot
    assert 'src="/static/js/account-panel.js?v=' in page(client, login, "/dashboard")
    for name in ["account-sphere-on-dark", "account-sphere-on-light"]:
        assert "layers" in client.get(f"/static/lottie/{name}.json").get_json()


def test_account_options_start_open_on_the_settings_page(client, login):
    foot, sphere, panel = account_parts(page(client, login, "/settings"))

    assert 'aria-expanded="true"' in sphere
    assert "is-open" in panel
