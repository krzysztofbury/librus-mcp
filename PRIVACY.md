# Privacy policy

librus-mcp is a local MCP server. It runs on your computer, started by your AI
assistant, and has no servers of its own. This policy covers the server and its
MCP Bundle; your AI assistant has its own policy.

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
- Tool results are returned to the AI assistant that called the tool. The
  assistant, and the model provider it uses, process them under their own
  privacy policies. Ask only for what you are comfortable sharing with them.
- There is no telemetry, analytics or crash reporting, and nothing is sent to
  the author or any other third party.
- Installing the server downloads it and its dependencies from PyPI, or Python
  through uv, as with any Python package.
- Sending messages to the school is off unless you enable it.

## What it stores on your computer

- A private state directory (default `~/.librus-mcp/state`) with a random key
  that protects references and cursors, and the notification history used to
  report what is new.
- Attachments you explicitly download (default `~/.librus-mcp/downloads`).

Both stay until you delete them; removing the server or the bundle does not
delete them.

## Contact

Questions go to the [issue tracker](https://github.com/krzysztofbury/librus-mcp/issues).
Report security problems privately as described in [SECURITY.md](SECURITY.md).
