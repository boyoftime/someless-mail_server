"""An iPhone's (or a Mac's) way to add a mailbox: a configuration profile, a file that sets up
the Mail app with the mailbox's address, server and ports. It holds no password: the iPhone asks
for it, and for the name to show on sent mail, while the profile is installed.

It's downloaded from the back of the mailbox's Configuration details, or on the iPhone itself:
its camera finds a link in the QR code there, which works for an hour, without a login (signed
with the panel's secret key, so it can't be made up or changed)."""
import plistlib
import time
import uuid

import segno
from flask import Response, current_app
from itsdangerous import BadSignature, URLSafeSerializer

KIND = "application/x-apple-aspen-config"
LINK_LASTS = 60 * 60   # seconds
SALT = "someless-mail-profile"


def _now():
    return time.time()


def profile(email, server, ports):
    """The profile, as bytes. Installing it again replaces the one before (the same identifiers)."""
    def made_for(part):
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"someless-mail:{server}:{email}:{part}")).upper()

    account = {
        "PayloadType": "com.apple.mail.managed",
        "PayloadVersion": 1,
        "PayloadIdentifier": f"someless.mail.{made_for('account')}",
        "PayloadUUID": made_for("account"),
        "PayloadDisplayName": email,
        "EmailAccountDescription": email,
        "EmailAccountType": "EmailTypeIMAP",
        "EmailAddress": email,
        "IncomingMailServerHostName": server,
        "IncomingMailServerPortNumber": ports["imap"],
        "IncomingMailServerUseSSL": True,
        "IncomingMailServerUsername": email,
        "IncomingMailServerAuthentication": "EmailAuthPassword",
        "OutgoingMailServerHostName": server,
        "OutgoingMailServerPortNumber": ports["smtp_ssl"],
        "OutgoingMailServerUseSSL": True,
        "OutgoingMailServerUsername": email,
        "OutgoingMailServerAuthentication": "EmailAuthPassword",
        "OutgoingPasswordSameAsIncomingPassword": True,
    }
    return plistlib.dumps({
        "PayloadType": "Configuration",
        "PayloadVersion": 1,
        "PayloadIdentifier": f"someless.mail.{made_for('profile')}",
        "PayloadUUID": made_for("profile"),
        "PayloadDisplayName": email,
        "PayloadDescription": f"Adds {email} to the Mail app. It asks for the mailbox's password.",
        "PayloadOrganization": "Someless Mail",
        "PayloadRemovalDisallowed": False,
        "PayloadContent": [account],
    })


def download(email, server, ports):
    return Response(profile(email, server, ports), mimetype=KIND, headers={
        "Content-Disposition": f'attachment; filename="{email}.mobileconfig"', "Cache-Control": "no-store"})


def _signer():
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt=SALT)


def new_link(mailbox_id):
    """The token for a link to the mailbox's profile, good for LINK_LASTS."""
    return _signer().dumps([mailbox_id, int(_now() + LINK_LASTS)])


def link_for(token):
    """The mailbox a link is for: its id, "expired", or None for a link that was made up."""
    try:
        mailbox_id, until = _signer().loads(token)
    except (BadSignature, TypeError, ValueError):
        return None
    return mailbox_id if _now() <= until else "expired"


def qr_code(url):
    """The link as a QR code, for the iPhone's camera: an SVG to put in the page."""
    return segno.make(url, error="m").svg_inline(scale=4, border=2, dark="#0f1a3d", light="#ffffff", omitsize=True)
