# Source excerpt: Node.js collaborator guide (published review policy)

Used only as the *owner statements* of the second fixture project ("fixture-b") so the two-project acceptance case is not built on invented preferences. Not a policy for any real pm-managed project.

- URL: https://raw.githubusercontent.com/nodejs/node/main/doc/contributing/collaborator-guide.md
- Retrieved: 2026-11-01T20:06:01Z; full-file sha256 c40666fb5f2fc2fbf10aaaa0de6d7aa1347e0f86b9e976961b517a13302836be
- Licence: Node.js documentation (MIT); short verbatim quotes.

## Lines 242-253 (section "Waiting for approvals")

```text
### Waiting for approvals

Before landing pull requests, allow 48 hours for input from other collaborators.
Certain types of pull requests can be fast-tracked and can land after a shorter
delay. For example:

* Focused changes that affect only documentation and/or the test suite:
  * `code-and-learn` tasks often fall into this category.
  * `good-first-issue` pull requests might also be suitable.
* Changes that fix regressions:
  * Regressions that break the workflow (red CI or broken compilation).
  * Regressions that happen right before a release, or reported soon after.
```

## Lines 434-446 (section "Breaking changes")

```text
### Breaking changes

At least two TSC voting members must approve backward-incompatible changes to
the `main` branch.

Examples of breaking changes include:

* Removal or redefinition of existing API arguments.
* Changing return values.
* Removing or modifying existing properties on an options argument.
* Adding or removing errors.
* Altering expected timing of an event.
* Changing the side effects of using a particular API.
```
