# DAEMON Serial Protocol: `serial-line-v1`

`serial-line-v1` is a newline-delimited ASCII protocol over a serial link (or socket bridge).

## Framing
- One command per line (`\n` terminated).
- UTF-8 text payload.
- Case-sensitive tokens.

## Host -> Node
- `HELLO`
- `READ_MANIFEST`
- `RUN <TOKEN> <arg0> <arg1> ...`
- `STOP`
- `SUB TELEMETRY`
- `UNSUB TELEMETRY`

## Node -> Host
- `MANIFEST <json>`
- `OK`
- `ERR <code> <message>`
- `TELEMETRY key=value key2=value2 ...`

## Behavioral requirements
- `READ_MANIFEST` must return the same manifest as `HELLO` bootstrap flow.
- `RUN` validates token and argument count/types against manifest.
- `STOP` must be idempotent and safe to call repeatedly.
- Telemetry messages are best-effort and must not block command responses.
