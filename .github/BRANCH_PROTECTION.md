# Main branch protection

The workflows in this directory provide merge checks. A repository ruleset must
also enforce them; workflow files cannot prevent direct pushes on their own.

After these workflows have run at least once, create an active branch ruleset in
**Settings > Rules > Rulesets** targeting `main` with:

- Restrict deletions
- Block force pushes
- Require a pull request before merging
- Require at least one approval
- Dismiss stale approvals when new commits are pushed
- Require conversation resolution before merging
- Require status checks to pass and branches to be up to date
  - `CI / Required`
  - `Security / Dependency audit`

Apply the rules to repository administrators too, and do not add bypass actors
unless an emergency process requires them.
