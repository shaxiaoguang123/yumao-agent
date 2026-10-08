# Sanitized `getUserInfo` Contract Evidence

- Evidence date: 2026-10-08
- Sources: ignored `req/` captures in the primary checkout and `req/1.js` official frontend bundle. Captures were read in memory; no raw Token, identity value, JWT payload, cookie, request/response body, or decryption material is recorded here.

## Observed Request and Success Contract

- Matched 4 request/response capture pairs for `POST https://bdtyg.cugb.edu.cn/service/appointment/appointment/userAddress/getUserInfo`.
- All four requests used `Content-Type: application/json`, a JSON body consisting of the empty object `{}`, and an authentication header named `token`. Header values are intentionally omitted.
- All four responses used HTTP 200 and the JSON envelope keys `success`, `message`, and `resultData`; each had `success=true`, `message=CORE10008`, and a `resultData` object with keys `idserial`, `tel`, and `username`.
- The successful response is direct JSON for this endpoint; no `item` request/response encryption envelope was observed in these four matched captures.

## Capability Results

- `token_validation_capability`: **supported by the observed contract and four successful known-token captures**. The exact request shape and success envelope are concrete enough for synthetic contract tests. This does not establish an invalid-Token mapping.
- `account_continuity_capability`: **supported for the observed Token replacement continuity use, with limited sample scope**. The four successful observations cover two distinct Token groups, two captures per group. The captured `idserial` comparison was equal within each group and across both groups. The official frontend bundle references `getUserInfo`, the endpoint path, `idserial`, the label `证件号`, and the relation of `idserial` to `reservationPerson`.
- These observations do not prove that `idserial` is globally unique across all upstream accounts or permanently stable for all future time. Those limits remain explicit; no username, telephone, display name, or fuzzy fallback is allowed.

## Unresolved Evidence and Runtime Gate

- No captured invalid-Token response was found among the four `getUserInfo` pairs. Until a separate exact mapping is evidenced, non-success responses remain `validation_unknown`/contract drift and cannot set `confirmed_invalid`.
- The matched request captures do not establish a reliable `getUserInfo` request-start interval. Response `Date` headers do not identify request-start timing. Do not reuse the unrelated approximately 668 ms observation. Keep `UPSTREAM_GET_USER_INFO_MIN_INTERVAL_MS` unset until endpoint-specific timing evidence is available; in that configuration the API must return `503 validation_not_configured` without persisting the submitted Token.

## Privacy Handling

The evidence note contains only field names, request/response shape, a non-secret success code, sample counts, and aggregate equality results. Raw captures, full Tokens, identity values, profile data, and decrypted content remain in the ignored local `req/` directory and were not copied into the worktree or Git.
