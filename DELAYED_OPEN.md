# v8.1.4 delayed availability retry

When the selected date has no available tee times, the bot retries Date_Click
for that same date for up to 90 seconds before moving to the next priority.
Each retry waits 2 seconds before requesting the date again; browser and server
response time is additional. An in-flight request can finish after the deadline.
Available times resume the existing nearest-time selection immediately.

This applies to test, safety-check and real booking modes. Submission guards
are unchanged. Stop interrupts the retry wait. Browser errors still propagate.
An empty date can also mean sold out: the bot cannot determine the cause,
and later priorities can therefore be delayed by the retry window.

The initial isolated build is `dist/v8.1.4/CastlexSeoul.exe` (not published).
The combined v8.1.5 release includes this behavior and the time strategies
documented in `RELEASE_NOTES_v8.1.5.md`.
Settings and saved accounts are loaded from the executable's own directory.

Validation: `py -3.13 -m unittest test_delayed_open -v`.
Tests simulate delayed opening, timeout, cancellation, browser failure and
submission guards. They do not perform a live reservation.
