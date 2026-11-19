# Separate users and shared clients

RecallFabric identifies a user by the `user_id` attached to the validated API key
or OAuth grant, not by the ChatGPT login, client name, conversation, or device.
Different OAuth tokens issued from the same account key still share one account.

For separate people, an administrator must provision a fresh random `user_id`
and account key for each person using the README's account provisioning procedure.
Keep each person's credential file separate and private. Never reuse the shared
demo account key for independent users. Public signup remains disabled.

For one person using multiple clients, authorize each client with that person's
account key. Each client receives its own OAuth grant while accessing the same
memory namespace. Do not share access or refresh tokens between clients.

If a tester previously authorized using somebody else's key, disconnect and revoke
the old grant before authorizing with their own key. Creating a new chat does not
change the account. Previously stored records stay with their original account;
do not automatically copy or reassign them.

## Verification

`tests/test_mcp_acceptance.py::test_concurrent_tenants_cannot_read_or_mutate_each_other`
uses the official MCP client, real PostgreSQL, and disposable migrated schemas.
It tests API-key credentials and resource-bound OAuth tokens separately, with
two accounts writing and reading concurrently through the same application.

Coverage: list, semantic recall, profile, profile resource, guessed-ID history,
provenance, update, deletion preview, confirmed deletion, and the delete alias.
After attempted attacks, both original records must retain their owner, content,
and version. Test embeddings deliberately match both accounts' content, so vector
relevance cannot accidentally conceal a missing ownership filter.

```powershell
$env:RECALLFABRIC_RUN_DB_TESTS = '1'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_mcp_acceptance.py -k concurrent_tenants
```

These tests validate server-side account isolation, not the account chosen by a
human in a real plugin's consent screen. Confirm that setup separately with one
fictional canary memory per person. Read `get_profile.user_id` to check which
account each connection actually represents; this is an identifier, not a secret.
