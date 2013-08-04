backupcopter
============

backupcopter is a backup tool which drives rsync, similar to rsnapshot.
It comes with the following features:

* ssh based backups (ssh support via rsync)
* per-target rate-limiting ssh (via trickle)
* per-target I/O-limiting rsync (via ionice)
* per-target atomic backups using btrfs snapshots
* backups on encrypted volumes (cryptsetup)
* incremental backups using ``cp -al`` or ``rsync --link-dest`` (the
  latter being preferred)

**Please note:** While I am using backupcopter in my daily routine and
I am trying to make sure it doesn't have any show-stopper bugs, I cannot
give any warranty that your backups actually work. **Always verify your
backups!** This of course also holds for backups not made with
backupcopter.

Usage
-----

Run ``./backupcopter.py --options`` for a manual on creating the
required configuration. Pagination (e.g. using ``less``) recommended.

After configuring, call ``./backupcopter.py`` with the intervals which
are to be run. For a daily backup (and an according configuration) e.g.
call ``./backupcopter.py daily``, at the end of the week you'll want to
call ``./backupcopter.py daily weekly`` and so on. backupcopter
automatically sorts the intervals and processes them at the correct
order. Always run backupcopter with all intervals which are to be
processed at one run for optimal performance.
