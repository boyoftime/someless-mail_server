"""Our own error pages instead of the plain ones Flask sends: "Page not found" with the 404
animation, everything else with the error animation. Signed in, the error shows in the main
area of the usual layout, menu and all; otherwise on a page of its own."""
from flask import Blueprint, current_app, g, jsonify, render_template, request, url_for
from flask_wtf.csrf import CSRFError
from werkzeug.exceptions import HTTPException

from .auth import load_admin

bp = Blueprint("errors", __name__)

# status code: (animation in static/lottie, title, text)
PAGES = {
    404: ("not-found", "Page not found",
          "There's nothing at this address. It may have been typed wrong, or the page has moved."),
    405: ("not-found", "This page can't be opened directly",
          "This address only works from a button in Someless Mail, not from the address bar."),
    500: ("error", "Something went wrong",
          "The server ran into a problem and couldn't finish this. Try again in a moment."),
}
# A form's security token was missing or too old (CSRFProtect)
EXPIRED = ("error", "This page has expired",
           "It was open for too long, or you logged out in another tab, so nothing was saved. "
           "Reload the page and try again.")
OTHER = ("error", "That didn't work", "The server couldn't complete this request. Go back and try again.")


@bp.app_errorhandler(HTTPException)
def show_error(error):
    # Unexpected crashes arrive here too, as a 500 (Flask wraps them).
    animation, title, text = EXPIRED if isinstance(error, CSRFError) else PAGES.get(error.code, OTHER)
    headers = {}
    if getattr(error, "valid_methods", None):  # 405: say which methods do work
        headers["Allow"] = ", ".join(error.valid_methods)
    # login-submit.js sends the login form in the background and asks for JSON. It shows
    # the message on its notice board, so keep it short.
    if request.accept_mimetypes.best == "application/json":
        return jsonify(error=f"{title}. Reload the page and try again."), error.code, headers
    page = {"code": error.code, "animation": animation, "title": title, "text": text}
    return _render(page), error.code, headers


def _render(page):
    if _signed_in():
        page.update(home_url=url_for("pages.dashboard"), home_label="Go to dashboard")
        try:
            return render_template("error-signed-in.html", page=page)
        except Exception:
            # The signed-in layout itself is what broke: the page on its own still works.
            current_app.logger.exception("Couldn't show the error page in the signed-in layout")
    else:
        page.update(home_url=url_for("auth.login"), home_label="Go to login")
    return render_template("error.html", page=page)


def _signed_in():
    # A rejected form (expired security token) is turned away before the admin is looked up.
    if "admin" not in g:
        try:
            load_admin()
        except Exception:
            current_app.logger.exception("Couldn't look up the admin for the error page")
            return False
    return g.admin is not None
