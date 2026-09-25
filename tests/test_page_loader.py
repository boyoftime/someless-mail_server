def test_signed_in_pages_show_a_loader_while_the_next_page_loads(client, login):
    login()
    html = client.get("/dashboard").get_data(as_text=True)

    assert '<dialog class="page-loader" id="page-loader"' in html
    assert 'data-loader-animation="/static/lottie/page-loader.json?v=' in html
    assert 'src="/static/js/page-loader.js?v=' in html
    assert "layers" in client.get("/static/lottie/page-loader.json").get_json()


def test_login_page_has_no_page_loader(client):
    assert "page-loader" not in client.get("/login").get_data(as_text=True)
