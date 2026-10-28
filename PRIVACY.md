# Privacy policy

librus-mcp is an MCP server that runs on a machine you control: your computer,
started by your AI assistant, or your own Docker host when you self-host it over
HTTP. It has no servers of its own and no hosted version. This policy covers
the server, its container image and its MCP Bundle; your AI assistant has its
own policy.

## What it handles

- **Your Librus Synergia login and password.** You provide them in a
  configuration file, as environment variables, or in your assistant's
  extension settings. A configuration file is restricted to your user account;
  an assistant that installs the MCP Bundle keeps them in its own settings
  store.
- **School data you ask for**: grades, attendance, timetable, homework,
  calendar, announcements, messages and attachments of the logins you
  configure. This usually concerns a child.

## Where it goes

- The server connects only to Librus services (`synergia.librus.pl`,
  `api.librus.pl`, `wiadomosci.librus.pl` and `sandbox.librus.pl` for
  attachment downloads), to sign in and to read what a tool call requests.
- When you self-host it over HTTP, tool results travel over your network to
  your agent. The server has no TLS of its own: use a reverse proxy with TLS or
  a private network, and keep the bearer token secret, since it grants every
  configured login.
- Tool results are returned to the AI assistant that called the tool. The
  assistant, and the model provider it uses, process them under their own
  privacy policies. Ask only for what you are comfortable sharing with them.
- There is no telemetry, analytics or crash reporting, and nothing is sent to
  the author or any other third party.
- Installing the server downloads it and its dependencies from PyPI, or Python
  through uv, as with any Python package.
- Sending messages to the school is off unless you enable it.
- When a tool call fails, the server writes one line to its standard error
  (which your assistant or Docker usually keeps in a log): the tool name, the
  error code, code locations and the versions. It never includes the login,
  alias, arguments or school data. The error result returned to the assistant
  holds the same code, locations and versions.
- If you set `LIBRUS_MCP_DIAGNOSE_FAILURES=1`, a failed read also writes the
  page structure around the failure to standard error: tags, known labels and
  lengths, with all page text and values masked. It is off by default; review
  it before sharing.

## What it stores on your computer

- A private state directory (default `~/.librus-mcp/state`, or `/data/state`
  in the container) with a random key
  that protects references and cursors, and the notification history used to
  report what is new.
- Attachments you explicitly download (default `~/.librus-mcp/downloads`, or
  `/data/downloads` in the container).

Both stay until you delete them; removing the server or the bundle does not
delete them.

## Contact

Questions go to the [issue tracker](https://github.com/krzysztofbury/librus-mcp/issues).
Report security problems privately as described in [SECURITY.md](SECURITY.md).
