"""The SMTP guide (/smtp/docs): sending mail through this server from code, with a working
example in six of the most used languages. Each example is filled in with the server's own
settings, and reads the key from the SOMELESS_SMTP_KEY environment variable, so it never
sits in the code. highlight() colours the code as HTML, the rest of it escaped."""
import re

from markupsafe import Markup, escape

# Each example: its tab (with the language's logo, static/img/lang, from Devicon), the file it
# would be, what to install first, and the code, where @SERVER@, @PORT@, @LOGIN@, @FROM@ and @TO@
# become the real values.
EXAMPLES = [
    {"key": "python", "name": "Python", "icon": "python", "file": "send.py", "install": None, "code": '''\
import os
import smtplib
from email.message import EmailMessage

message = EmailMessage()
message["From"] = "@FROM@"
message["To"] = "@TO@"
message["Subject"] = "Hello from Someless Mail"
message.set_content("It works!")

with smtplib.SMTP("@SERVER@", @PORT@) as smtp:
    smtp.starttls()  # encrypted before the login goes out
    smtp.login("@LOGIN@", os.environ["SOMELESS_SMTP_KEY"])
    smtp.send_message(message)
'''},
    {"key": "node", "name": "Node.js", "icon": "nodejs", "file": "send.mjs", "install": "npm install nodemailer", "code": '''\
import nodemailer from "nodemailer";

const transport = nodemailer.createTransport({
  host: "@SERVER@",
  port: @PORT@,
  secure: false, // starts plain, then STARTTLS...
  requireTLS: true, // ...before the login goes out
  auth: { user: "@LOGIN@", pass: process.env.SOMELESS_SMTP_KEY },
});

await transport.sendMail({
  from: "@FROM@",
  to: "@TO@",
  subject: "Hello from Someless Mail",
  text: "It works!",
});
'''},
    {"key": "php", "name": "PHP", "icon": "php", "file": "send.php", "install": "composer require phpmailer/phpmailer", "code": '''\
<?php
use PHPMailer\\PHPMailer\\PHPMailer;

require "vendor/autoload.php";

$mail = new PHPMailer(true);
$mail->isSMTP();
$mail->Host = "@SERVER@";
$mail->Port = @PORT@;
$mail->SMTPSecure = PHPMailer::ENCRYPTION_STARTTLS;
$mail->SMTPAuth = true;
$mail->Username = "@LOGIN@";
$mail->Password = getenv("SOMELESS_SMTP_KEY");

$mail->setFrom("@FROM@");
$mail->addAddress("@TO@");
$mail->Subject = "Hello from Someless Mail";
$mail->Body = "It works!";
$mail->send();
'''},
    {"key": "java", "name": "Java", "icon": "java", "file": "SendMail.java", "install": "Maven: org.eclipse.angus:angus-mail", "code": '''\
import jakarta.mail.*;
import jakarta.mail.internet.*;
import java.util.Properties;

public class SendMail {
    public static void main(String[] args) throws MessagingException {
        Properties settings = new Properties();
        settings.put("mail.smtp.host", "@SERVER@");
        settings.put("mail.smtp.port", "@PORT@");
        settings.put("mail.smtp.auth", "true");
        settings.put("mail.smtp.starttls.enable", "true");
        settings.put("mail.smtp.starttls.required", "true");

        Session session = Session.getInstance(settings, new Authenticator() {
            @Override
            protected PasswordAuthentication getPasswordAuthentication() {
                return new PasswordAuthentication("@LOGIN@", System.getenv("SOMELESS_SMTP_KEY"));
            }
        });

        Message message = new MimeMessage(session);
        message.setFrom(new InternetAddress("@FROM@"));
        message.setRecipients(Message.RecipientType.TO, InternetAddress.parse("@TO@"));
        message.setSubject("Hello from Someless Mail");
        message.setText("It works!");
        Transport.send(message);
    }
}
'''},
    {"key": "csharp", "name": "C#", "icon": "csharp", "file": "Program.cs", "install": "dotnet add package MailKit", "code": '''\
using MailKit.Net.Smtp;
using MailKit.Security;
using MimeKit;

var message = new MimeMessage();
message.From.Add(MailboxAddress.Parse("@FROM@"));
message.To.Add(MailboxAddress.Parse("@TO@"));
message.Subject = "Hello from Someless Mail";
message.Body = new TextPart("plain") { Text = "It works!" };

using var smtp = new SmtpClient();
await smtp.ConnectAsync("@SERVER@", @PORT@, SecureSocketOptions.StartTls);
await smtp.AuthenticateAsync("@LOGIN@", Environment.GetEnvironmentVariable("SOMELESS_SMTP_KEY"));
await smtp.SendAsync(message);
await smtp.DisconnectAsync(true);
'''},
    {"key": "go", "name": "Go", "icon": "go", "file": "main.go", "install": None, "code": '''\
package main

import (
	"log"
	"net/smtp"
	"os"
)

func main() {
	auth := smtp.PlainAuth("", "@LOGIN@", os.Getenv("SOMELESS_SMTP_KEY"), "@SERVER@")
	message := []byte("From: @FROM@\\r\\n" +
		"To: @TO@\\r\\n" +
		"Subject: Hello from Someless Mail\\r\\n" +
		"\\r\\n" +
		"It works!\\r\\n")
	// SendMail switches to TLS (STARTTLS) before logging in
	err := smtp.SendMail("@SERVER@:@PORT@", auth, "@FROM@", []string{"@TO@"}, message)
	if err != nil {
		log.Fatal(err)
	}
}
'''},
]

KEYWORDS = {
    "python": "import from with as def return True False None",
    "node": "import from const await new true false",
    "php": "use require new true false",
    "java": "import public class static void throws new return protected",
    "csharp": "using var new await true",
    "go": "package import func var if return nil",
}


def examples(server, port, login, sender, recipient="friend@example.org"):
    """The examples, filled in with these settings."""
    filled = []
    for example in EXAMPLES:
        code = example["code"]
        for token, value in (("@SERVER@", server), ("@PORT@", str(port)), ("@LOGIN@", login),
                             ("@FROM@", sender), ("@TO@", recipient)):
            code = code.replace(token, value)
        filled.append({**example, "code": code, "html": highlight(code, example["key"])})
    return filled


def highlight(code, language):
    """The code as HTML: comments, strings, keywords and numbers in spans, the rest escaped."""
    comment = r"#[^\n]*" if language == "python" else r"//[^\n]*"
    words = "|".join(KEYWORDS[language].split())
    pattern = re.compile(
        rf"(?P<comment>{comment})|(?P<string>\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*')"
        rf"|(?P<keyword>\b(?:{words})\b)|(?P<number>\b\d+\b)")
    parts, at = [], 0
    for match in pattern.finditer(code):
        parts.append(escape(code[at:match.start()]))
        parts.append(Markup('<span class="code-{}">{}</span>').format(match.lastgroup, match.group()))
        at = match.end()
    parts.append(escape(code[at:]))
    return Markup("").join(parts)
