# Notifications

Settings → Notifications. Each connection chooses its events:

| Event | When |
|---|---|
| Grab | a release was sent to a download client (by RSS sync, the backlog, a search, a retry) |
| Import | a download was filed in the library |
| Upgrade | a better file replaced an existing one |
| Failure | a download failed, or a finished download couldn't be imported |
| Health problem | a health check found a new problem |

| Service | You need |
|---|---|
| Discord | a channel webhook URL (Channel settings → Integrations → Webhooks) |
| Slack | an incoming webhook URL |
| ntfy | a topic (and the server, if not ntfy.sh; a token for protected topics) |
| Pushover | your user key and an application's API token |
| Webhook | a URL that accepts a JSON POST |

Messages are sent only after the change behind them is saved: a grab that fails half-way never
says "Grabbed".

## Templates

Each event's message is a template: the first line is the title, the rest the message. Tokens:
`{magazine}`, `{issue}`, `{release}`, `{quality}`, `{client}`, `{source}` (RSS sync, backlog
search, manual grab...), `{path}`, `{message}`, `{event}`. Leave a template blank for the default;
*Preview* shows it with example values.

The webhook's JSON has `event`, `title`, `message` and every token's value.
