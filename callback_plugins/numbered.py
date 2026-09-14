"""Built-in `default` stdout callback plus a running number on every task banner.

    TASK [control_plane_init : init | Run kubeadm init]      <- default
    TASK 93 [control_plane_init : init | Run kubeadm init]   <- numbered

Enabled in ansible.cfg (`stdout_callback = numbered`). Everything else —
callback_result_format=yaml, display_skipped_hosts, colours, the recap — is the
default callback unchanged, because this subclasses it and only touches the
banner text.
"""

from __future__ import annotations

DOCUMENTATION = """
    name: numbered
    type: stdout
    short_description: default output with a running number on each task banner
    description:
        - Identical to the built-in C(default) stdout callback, except every
          C(TASK [...]) and C(RUNNING HANDLER [...]) banner carries a running
          number, for example C(TASK 93 [Run kubeadm init]).
        - Only banners that are actually printed are counted. With
          C(display_skipped_hosts = False), a task skipped on every host prints
          no banner and gets no number, so the sequence never has gaps.
    extends_documentation_fragment:
      - default_callback
      - result_format_callback
    requirements:
      - set as the stdout callback in ansible.cfg
"""

from ansible.plugins.callback.default import CallbackModule as DefaultCallbackModule


class CallbackModule(DefaultCallbackModule):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "stdout"
    CALLBACK_NAME = "numbered"

    def __init__(self):
        super().__init__()
        self._task_number = 0

    def _print_task_banner(self, task):
        # The default callback builds the banner as "<PREFIX> [<name>...]" and
        # hands it to Display.banner(). Rather than copy that formatting (it
        # differs slightly between ansible-core releases), wrap banner() for
        # this one call and insert the number before the first " [".
        self._task_number += 1
        number = self._task_number
        display = self._display
        had_instance_banner = "banner" in vars(display)
        original_banner = display.banner

        def numbered_banner(msg, *args, **kwargs):
            prefix, sep, rest = msg.partition(" [")
            if sep:
                msg = f"{prefix} {number} [{rest}"
            return original_banner(msg, *args, **kwargs)

        display.banner = numbered_banner
        try:
            super()._print_task_banner(task)
        finally:
            if had_instance_banner:
                display.banner = original_banner
            else:
                del display.banner
