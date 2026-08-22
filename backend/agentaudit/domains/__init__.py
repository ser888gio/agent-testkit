"""Built-in verticals. Importing this package registers every sandbox it ships.

`core.sandbox.load_builtin_sandboxes` imports this module by name and nothing
else, so a new built-in vertical is added here -- one line, beside the code it
registers -- and `core/` stays unchanged. Third-party sandboxes are unaffected:
they register by being imported, exactly as before.
"""

from agentaudit.domains.email import sandbox as _email_sandbox  # noqa: F401
from agentaudit.domains.treasury import sandbox as _treasury_sandbox  # noqa: F401
