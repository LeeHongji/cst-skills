# Lint codes

- `missing_frontmatter`: required identity or lifecycle metadata is absent.
- `invalid_status`: lifecycle status is outside the controlled vocabulary.
- `validated_without_evidence`: a validated page has neither evidence nor sources.
- `duplicate_id`: stable identity collision; must be resolved.
- `duplicate_filename`: Obsidian wikilink may be ambiguous.
- `broken_wikilink`: target page is absent or misspelled.

Warnings can remain only when their rationale is documented. Errors block a clean audit.
