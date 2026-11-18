# MCP invocation guidance

Guidance-only update: tool schemas, annotations, authentication, OAuth origins, embedding
model, relevance threshold, extraction and memory services are unchanged.

Previously recall/get_profile encouraged use at conversation start, remember broadly
encouraged saving durable facts, and use_memory lacked continuity examples, exclusions,
current-user precedence and recommendation-acceptance rules. History/provenance and legacy
aliases overlapped without clear selection guidance.

Recall now names continuation/resumption, named projects/topics, prior decisions, preferences,
constraints and cross-client continuity. Search before asking the user to repeat context;
skip general knowledge, unrelated topics and trivial self-contained requests.

Remember/update distinguish explicit durable user facts and accepted decisions from casual,
temporary or speculative content and unaccepted assistant recommendations. Profile/inventory
and revision/source-history tools explain when each is appropriate. Deletion safety is unchanged.

Server initialization instructions and use_memory reinforce fallible/untrusted memory,
current-statement precedence, relevance, restrained narration and clarification only when
ambiguity remains. Examples cover Orion, stack decisions, notebook color, binary search,
merge sort, personal overview and a direct SQLite correction.

All 11 tools remain public for compatibility. Aliases explicitly prefer recall/remember/forget;
hiding them was not established safe for existing clients. The profile resource URI is unchanged.

## Verification

54 focused tests passed; Ruff and whitespace checks passed. After backend-only reload,
public SDK initialization, tool/prompt/resource discovery and authenticated recall passed.
All tool contracts excluding descriptions and OAuth discovery JSON matched the baseline.
/ready returned 200; unauthenticated /mcp/ remained 401. cloudflared PID 35196 and its
start time remained unchanged. No reconnect/reauthorization, commits or pushes were performed.

ChatGPT real-client scenarios remain untested because browser access is unavailable.
Claude's window was visible, but Computer Use rejected access as not approved for Claude.
No automatic-invocation pass/fail or improvement rate can be inferred from protocol tests.

## Manual acceptance in fresh chats

Keep RecallFabric enabled. Inspect actual tool activity for each prompt in both clients:

| Prompt | Expected |
|---|---|
| Let's continue working on Project Orion. | Recall Orion before asking for repeated context |
| What technology stack did we decide on? | Recall relevant project decisions |
| What color is my notebook? | Recall notebook memory |
| Explain merge sort. | No unnecessary memory lookup |
| What do you remember about me? | Profile or inventory as appropriate |
| Actually, we're using SQLite now. | Direct user correction; resolve target and use current version |

Use a synthetic project for the SQLite test, not unrelated existing project decisions.
Client metadata caches, tool enablement, model selection and whether prompts are loaded
can affect behavior. Guidance cannot guarantee calls or suppress every unnecessary call.

For ChatGPT custom MCP connections, the documented metadata refresh workflow is Plugins ->
RecallFabric -> Refresh, then start a fresh conversation. This is not disconnect/reconnect
or OAuth reauthorization. Do not remove a working connection to refresh descriptions.

Official guidance:
https://developers.openai.com/plugins/deploy/connect-chatgpt
https://developers.openai.com/plugins/guides/optimize-metadata
