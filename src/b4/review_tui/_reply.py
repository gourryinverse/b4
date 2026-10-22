#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2024 by the Linux Foundation
#
"""Reply to one message from any Textual app: edit, preview, send.

The thread viewer uses this, and so can other front ends that show mail
and want b4's reply behaviour -- the quoted editor text, the preview
that shows the real outgoing message, and delivery with the user's mail
configuration -- without copying it.
"""

import email.message
from typing import Any, Callable, Optional

from textual.app import App

import b4
from b4.review.messages import mark_outgoing_seen
from b4.review_tui._common import prepare_followup_reply_body, suspend_and_edit
from b4.review_tui._modals import FollowupReplyPreviewScreen

logger = b4.logger


def reply_quote(lmsg: 'b4.LoreMessage') -> str:
    """The editor's starting text: an attribution line and the quoted body."""
    orig_date = lmsg.date.strftime('%Y-%m-%d %H:%M %z') if lmsg.date else ''
    orig_author = lmsg.fromname or lmsg.fromemail
    body = lmsg.body or ''
    quoted = '\n'.join(f'> {line}' for line in body.splitlines())
    return f'On {orig_date}, {orig_author} wrote:\n{quoted}\n\n'


def send_followup_reply(
    app: 'App[Any]',
    lmsg: 'b4.LoreMessage',
    text: str,
    *,
    email_dryrun: bool = False,
    patatt_sign: bool = True,
) -> Optional[email.message.EmailMessage]:
    """Build and send a reply to *lmsg*; return it, or ``None`` if it failed.

    Failures are reported through a notification.  A real send is marked
    Seen and Sent, so it does not show up as unread once it reaches the list.
    """
    text = prepare_followup_reply_body(text)
    msg = lmsg.make_reply(text)
    try:
        with app.suspend():
            smtp, fromaddr = b4.get_smtp(dryrun=email_dryrun)
            sent = b4.send_mail(
                smtp,
                [msg],
                fromaddr=fromaddr,
                patatt_sign=patatt_sign,
                dryrun=email_dryrun,
                output_dir=None,
                reflect=False,
            )
    except Exception as ex:
        app.notify(f'Send failed: {ex}', severity='error')
        return None
    if sent is None:
        app.notify('Failed to send reply.', severity='error')
        return None
    if email_dryrun:
        app.notify(f'Dry-run: reply to {lmsg.fromemail} logged, not sent')
    else:
        mark_outgoing_seen([msg])
        app.notify(f'Reply sent to {lmsg.fromemail}')
    return msg


def compose_followup_reply(
    app: 'App[Any]',
    lmsg: 'b4.LoreMessage',
    *,
    email_dryrun: bool = False,
    patatt_sign: bool = True,
    on_sent: Optional[Callable[[email.message.EmailMessage], None]] = None,
    initial_text: Optional[str] = None,
    topdir: Optional[str] = None,
) -> None:
    """Edit a reply to *lmsg* in the user's editor, preview it, and send it.

    *on_sent* runs with the outgoing message once it has been sent (or
    logged, in a dry run); the caller records whatever it tracks, such as
    an Answered flag.
    """
    editor_text = reply_quote(lmsg) if initial_text is None else initial_text
    result = suspend_and_edit(app, editor_text.encode(), 'reply.eml', topdir=topdir)
    if result is None:
        return
    reply_text = result.decode(errors='replace')
    if reply_text == editor_text:
        app.notify('No changes made')
        return

    # The fields FollowupReplyPreviewScreen expects
    entry = {
        'lmsg': lmsg,
        'fromname': lmsg.fromname,
        'fromemail': lmsg.fromemail,
        'date': lmsg.date,
        'body': lmsg.body or '',
    }

    def _on_preview(action: Optional[str]) -> None:
        if action == 'send':
            msg = send_followup_reply(
                app,
                lmsg,
                reply_text,
                email_dryrun=email_dryrun,
                patatt_sign=patatt_sign,
            )
            if msg is not None and on_sent is not None:
                on_sent(msg)
        elif action == 'edit':
            compose_followup_reply(
                app,
                lmsg,
                email_dryrun=email_dryrun,
                patatt_sign=patatt_sign,
                on_sent=on_sent,
                initial_text=reply_text,
                topdir=topdir,
            )

    app.push_screen(FollowupReplyPreviewScreen(entry, reply_text), _on_preview)
