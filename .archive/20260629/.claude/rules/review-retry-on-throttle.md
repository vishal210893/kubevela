# Retry Throttled Bedrock Calls

**When to use this rule**: After dispatching review perspective calls via review-cli.py or review-bedrock.py.

## Rule

After ALL parallel Bash calls complete, you MUST check whether every requested perspective succeeded before proceeding to synthesis. Do NOT skip this check.

## How to check

```bash
for f in .reviews/.result-*.json; do
  python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('status','?'), d.get('focus','?'), (d.get('error') or '')[:80])" "$f"
done
```

## Decision

- **All completed**: Proceed to synthesis.
- **Some failed with retriable errors** (error message contains "throttl", "rate", "timeout", "503", "network", "expired", "credentials", "ExpiredToken", or "ExpiredTokenException"): Wait 30 seconds, then re-dispatch ONLY the failed perspectives using the same model, profile, region, and context as the original dispatch. Maximum 2 retry rounds.
- **Failed with non-retriable errors** (access denied, validation, model not found): Do NOT retry. Report these to the user and proceed with the perspectives that succeeded.
- **All failed**: Report the error to the user. Do not proceed to synthesis.

## After retries

If some perspectives still fail after 2 retry rounds, tell the user which ones failed and why, then synthesize from whatever succeeded. Do not silently drop failures.

If failures contain credential/token expiry keywords (`expired`, `credentials`, `ExpiredToken`), tell the user their AWS SSO session may have expired and suggest refreshing credentials (e.g., `aws sso login --profile <profile>`) before retrying.
