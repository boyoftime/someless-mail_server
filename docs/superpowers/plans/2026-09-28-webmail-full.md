# The full webmail — plan and progress

**Goal:** the webmail (port 17090) becomes a complete mail client that matches PrivateEmail
(Namecheap's webmail) in how it looks and how it works, on the user's own mail: mail, compose,
search, settings, contacts and calendar, with new mail arriving on its own (and a sound).
Someless branding, our own icons and code.

**Asked for by the user (2026-09-28):** "any feature from private mail and how it works, style
and functionality, we should make the same… compose window should look the same… now build it
fully."

## Decisions

1. **Mail comes from the engine over JMAP** (RFC 8620/8621; Stalwart 0.16.23 has mail,
   submission, vacation, sieve, contacts, calendars, quota and WebSocket push). The webmail signs
   in *as the mailbox* through its own engine account, `someless-webmail@someless.internal`,
   which has the `impersonate` permission: login `mailbox@domain%someless-webmail@someless.internal`
   with the webmail's password (`engine.webmail_password`). Its credential only works from
   127.0.0.1 (`allowedIps`), so only the container can use it. No mailbox password is kept.
   Spiked OK against the real engine (scratchpad/spike_webmail_jmap.py).
2. **Folders as PrivateEmail names them:** Inbox, Drafts, Sent, Archive, Spam, Trash (engine
   roles inbox, drafts, sent, archive, junk, trash), then the mailbox's own folders as a tree.
   Archive is made the first time it's needed (the engine has none by default).
3. **Server-rendered HTML, small JS controllers** (as the rest of the app): the server sends
   rows, the reader and panels as HTML; the page swaps them in. No build step.
4. **A message's HTML is sanitized (nh3), then shown in a sandboxed frame** (no scripts, CSP
   `default-src 'none'`), links cleaned of tracking codes (PrivateEmail's shield count), inline
   `cid:` images served by the webmail. Dark theme: colours adapted from the computed styles
   (the sun shows the message's own colours). Attachments are served inline only for images
   and PDFs; anything else downloads, with nosniff.
5. **New mail on its own:** a WebSocket from each open webmail page (flask-sock); the webmail
   listens to the engine's JMAP push for that mailbox and passes changes on; the page fetches
   what's new, plays the user's sound (digitalstore07-modern-short-message-tone-430435.mp3,
   Pixabay) and can show a desktop notification. Nginx Proxy Manager needs "Websockets Support".
6. **Matching PrivateEmail:** its public bundles on spaceship-cdn.com (listed in the ILC
   registry of https://privateemail.com/login/) hold its CSS values and its English labels
   (`scratchpad/pe-ref/labels.js` extracts them by key path). Screens are rebuilt from those
   values, not copied: our markup, our CSS, our icons. The user's PrivateEmail login is not used.

## Phases

- [x] **1. Real mail** — engine account + JMAP client; folders (tree, counts, create/rename/
  move/delete, empty, mark all read); the list (50 at a time, selection, bulk actions, right-click
  menu, drag to a folder, filter menu); the reader (HTML/text, attachments with preview and save
  all, tracking-link cleaning, view source, download, print); mark read/unread, favorite,
  archive, delete, spam/not spam, move; search (panel with recent searches, results page);
  storage from the engine's quota; the preview's made-up mail goes.
- [x] **2. Compose** — PrivateEmail's composer windows (several, minimise, full screen), To/Cc/
  Bcc chips with suggestions, rich text (formatting toolbar, links, images), attachments, drafts
  saved as you type, send (EmailSubmission), reply / reply all / forward (also inline in the
  reader), mark important, signatures inserted.
- [x] **3. New mail on its own** — WebSocket + engine push, the sound, notifications, unread
  count in the tab's title.
- [x] **4. Settings** — profile (display name, address), keyboard shortcuts, signatures,
  auto-reply (VacationResponse), forwarding and filters (Sieve), spam, third-party apps
  (IMAP/SMTP/CalDAV/CardDAV settings), security (password), system preferences (theme).
- [x] **5. Contacts** — address books and contacts (JMAP ContactCard), as PrivateEmail's app.
- [x] **6. Calendar** — calendars and events (JMAP CalendarEvent), month / week / day, the event
  editor, invitations, as PrivateEmail's app.

## How it's tested

- Unit tests with a made-up JMAP engine (`tests/jmap_fake.py`) for every view and action.
- Live tests against the real engine (`STALWART_BIN`), for the JMAP client, sending and push.
- Chrome checks at the user's screen (1536 × 743 CSS px at 125%), both themes and a phone.

## Progress

(Newest last. One line per finished piece: what, and the tests.)
- 2026-09-29 Phase 1, real mail: folders (PrivateEmail's order, menus, folding, four levels, "Sort alphabetically"),
  the list (50 at a time, each folder's own sort and filters), the reading pane (dark colours for light mail, attachments
  with previews, links cleaned of tracking, source, print), ticks and the panel for two or more, the right-click menu,
  drag to folders, search with its panel and recent searches, folders without a new page. tests/test_webmail.py (117).
- 2026-09-29 Phase 2, compose: windows (up to five, minimize, full screen), replies under the message, To/Cc/Bcc chips
  with suggestions, the formatting bar, files and pictures, signatures, drafts saved as it's written, sending with
  EmailSubmission. tests/test_webmail_compose.py (33).
- 2026-09-29 Phase 3, new mail as it comes: /live (flask-sock) relays the engine's EventSource; the new-mail sound,
  notifications, the list and the tab's count follow. tests/test_webmail_live.py (4).
  Found: the engine's own auto-reply (VacationResponse) switches the mailbox's Sieve script off, so Settings writes
  one script of its own with the filters, forwarding and auto-reply in it (webmail/sieve.py).
- 2026-09-29 Phase 4, Settings: the cards page (Profile, System preferences, Signature, Forwarding, Filters, Auto-reply,
  Spam, Third-party apps, Security Center), signatures, the auto-reply between two dates, forwarding, filters (conditions
  all/any/none with a nested group, actions, stop, dragged into order), a new password ("Save & log out"), the logins,
  Connect third-party apps (IMAP/POP3/SMTP, CalDAV/CardDAV, an Apple profile). tests/test_webmail_settings.py (86).
  Found on the real engine: `fileinto :mailboxid` needs "mailbox" required as well; every condition and action was
  written into a script the engine took, and a filter moved, read-marked and starred a delivered message.
  Found: the zone cookie arrives as Africa%2FNairobi, which the server never decoded (mail times were UTC): fixed
  (messages.zone_name), tests/test_webmail.py.
- 2026-09-29 Phase 5, Contacts: the address book (JMAP ContactCard, JSContact cards), by name a page at a time, found as
  it's typed, Contact details, the form with emails, phones, addresses, job, birthday, notes and a photo; ticked ones
  deleted, all of them across the pages too; the compose window suggests them. tests/test_webmail_contacts.py (32).
  The engine sorts cards only by when they were made and finds whole words only, so the webmail sorts and searches.
- 2026-09-29 Phase 6, Calendar: Daily / Workdays / Weekly / Monthly, the month down the side, calendars shown, hidden,
  renamed and coloured; events in the reader's time, all day or timed, repeating (a custom rule too), people invited
  (the engine sends the invitations), one time of a repeat or all of them changed or deleted, invitations answered.
  tests/test_webmail_calendar.py (55). Found: the engine has the newer JMAP Calendars (one `recurrenceRule`, the times of
  a repeat with ids of their own), and tells which series a time is of only when baseEventId is asked for by name.
- 2026-09-29 Calendar and contacts apps: /dav/ and /.well-known/caldav|carddav through the webmail's own address, the
  password checked here with the sign-in lock, then on to the engine as the mailbox. tests/test_webmail_dav.py (14).
  On the real engine: a vCard written over CardDAV showed in Contacts.
