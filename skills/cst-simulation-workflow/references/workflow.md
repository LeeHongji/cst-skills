# Task lifecycle

Start with the topic, design and attempt contracts, explicit objectives,
bounded parameter ranges and deterministic model adapter. The topic router
selects the registered data project from this workspace's system/projects.json. Unknown or ambiguous ownership is an error.

1. Query Brain for applicable evidence.
2. Submit an offline CAD audit; inspect geometry and DRC.
3. Bind approval to the audited attempt and ranges.
4. Submit a simulation request; Guardian owns preparation, save, solve,
   convergence checks, export and independent cache-free reopen.
5. Query terminal job, acceptance, immutable artifacts and learning receipt.

For sweeps, enumerate candidates and cost before submission, and use one
request per candidate. For optimization, use the same loop with a bounded
candidate planner; no runtime wrapper or manual Lab locking is necessary.
Uncertain retries reuse request_id. Fresh confirmations use fidelity=confirm.

For existing CST files, never imply a generic live-edit capability: first
verify there is a supported adapter and source-copy/readback path. If not,
report the missing capability and develop it explicitly. Do not silently
reconstruct a user's source or attach to an unrelated live session.

Reports include objective, topic/design/attempt, job references, parameters,
setup changes, source hashes, convergence, exported data, acceptance,
publication state, and unresolved limitations.
