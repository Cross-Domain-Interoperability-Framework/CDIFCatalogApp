# Scientist sessions: how to run them

Day 10 of the spike build plan in [design.md](design.md). Three sessions of 30 minutes, each with
one scientist who has not seen CDIF, thinking aloud while they describe a dataset in the form.

The sessions answer one question: **can a domain scientist submit a valid record through the form
without help?** Everything below serves that question. Nothing here has been tried in a session
yet; correct it after the first one.

## What is still to settle

These are assumptions in this guide, not decisions. Change the guide if they are wrong.

- **Each scientist describes a dataset of their own**, which they bring. A dataset they know is the
  fair test of the form; a made-up one tests reading comprehension instead.
- **Signing in is part of the session.** The plan puts ORCID sign-in in scope. It costs set-up
  (see the next section), and a session can be run without it: the form saves without sign-in.
- **The sessions use the hosted prototype** at `https://cdif-catalog.onrender.com`, not a
  developer's machine.

## Before the day

Do these in the week before, not on the morning.

| Check | Why |
|---|---|
| Three scientists booked, none of whom has seen CDIF or this form | The plan's condition. Someone who helped build or test it does not count. |
| Each asked to bring one dataset of their own: its title, who made it, where it can be got, and its DOI if it has one | So the session is spent on the form, not on remembering. Ask for one **with** a DOI from at least one person and one **without** from at least one, so both ways of starting are seen. |
| A sandbox ORCID account for each scientist, made by you, with its sign-in details on a card | The prototype signs in through ORCID's sandbox, whose accounts are separate from real ORCID accounts. A scientist's own ORCID password will not work, and registering takes minutes and a throwaway email address (see [setup-sandboxes.md](setup-sandboxes.md)). Making one in the session would use up the time and test ORCID, not the form. |
| The database's deletion date | On the free plan the database is deleted 30 days after it was made ([deploy-render.md](deploy-render.md)). Hold the sessions before then, or move the plan. |
| Whether author search finds real people | Search for a real colleague in the "Authors" picker. If nobody real is found, the server is searching the sandbox (`ORCID_API_BASE`), and every scientist will fail to find themselves. |
| A full run by you, start to finish, on the hosted prototype | The dry run was by script ([form-inventory.md](form-inventory.md)). Nobody has yet entered a whole record by hand there. Do not let the first session be the first time. |
| A way to record the screen and voice, with the scientist's agreement | Notes miss what a person said just before they got stuck. |

Ten minutes before each session: open the prototype so it is awake (it sleeps after 15 minutes
without a visitor and takes about a minute to wake), sign out, and press "Start a new record".

## The session, minute by minute

| Minutes | What happens |
|---|---|
| 0 to 3 | Welcome. Read the introduction below. Start the recording. |
| 3 to 5 | Hand over the task sheet and the sign-in card. Start the clock when they first touch the form. |
| 5 to 25 | They work. You watch, take notes, and say almost nothing (see "What you may say"). |
| 25 to 30 | Stop them if they have not finished. Ask the closing questions. |

Twenty minutes of working time is the pass mark, so do not let the working time run on to be kind.
Note where they were when the clock stopped.

### Introduction, to read aloud

> Thank you for doing this. We are testing a form, not you. If something is confusing, that is the
> form's fault and exactly what we need to see.
>
> I am going to ask you to describe one of your datasets in this form, as if you were adding it to
> a catalogue so that other people can find it. Please think aloud as you go: say what you are
> looking for, what you expect a button to do, what you think a label means.
>
> I will not be able to help or answer questions while you work, because we need to see what
> happens when nobody is there to ask. If you are stuck, say so, try what you would try on your
> own, and move on if you want to. You can stop at any time.

### Task sheet, to hand over

> **Describe your dataset**
>
> 1. Open the form at the address on your card and sign in with the details on the card.
> 2. Describe the dataset you brought, so that someone else could find it and get hold of it.
> 3. When you think the description is good enough, check it and submit it.
>
> There is no right amount of detail. Fill in what you would fill in if this were real.

The task sheet deliberately does not name any field, tab or button other than what a person must
be told to begin. Do not add hints to it.

## What you may say

The pass mark is "unaided", so what counts as aid has to be fixed before the first session and
kept the same for all three.

**Not help. Say these freely.**

- "What are you looking for?" "What did you expect to happen?" "Keep talking."
- "That is up to you." "Do what you would do if I were not here."
- Anything about the room, the recording, the time left, or the sandbox sign-in card.

**Help. If you say any of these, write it on the observation sheet with the time.**

- Where a field, tab or button is.
- What a label, a message or a word means.
- What to type, or what format to type it in.
- That something they did was right or wrong.

One piece of help does not end the session; it changes its result from "unaided" to "aided".
Give help only when the scientist would otherwise stop, and give the least that gets them moving.

**A fault in the prototype is not the scientist's failure.** If the page stops working, the
save fails, or sign-in breaks, stop the clock, fix it or work round it, note it, and start the
clock again.

## Observation sheet

One per session. Fill in the top before, the middle during, the bottom straight after.

```
Session:            Date:            Scientist's field:
Dataset has a DOI:  yes / no         Used "Fill from DOI":  yes / no / tried and it failed

Clock started:               Record first checked:            Submitted:
Times "Check my record" was pressed:
"Must be fixed" count at first check:          at last check:

Moments of trouble (one line each)
  time | where (tab, field) | what they said or did | how it ended (got past it / gave up / helped)
  -----|--------------------|-----------------------|-----------------------------------------------

Help given (one line each)
  time | what was said | why

Faults in the prototype (one line each)
  time | what happened

Things they filled in wrongly without noticing:

Things they wanted to say about the dataset and found no place for:
```

After the session, open the record they made and note two more things the scientist cannot tell
you: whether the description is one a stranger could find the dataset by, and anything saved
that they did not mean (a default they never saw, text in the wrong field).

### Closing questions

- What was the hardest part?
- Was there anything you wanted to say about your dataset that the form gave you no place for?
- Was there anything it asked for that you did not understand, or did not see the point of?
- When the form told you something needed fixing, did you know what to do?
- Would you do this again for your next dataset without being asked to?

## What to watch for

The dry run and the form inventory found these. They are known, so the question in a session is
not whether they exist but whether they stop a scientist.

- **Downloads.** Adding a download opens some twenty fields with labels such as "Schema Content
  Url". A record is valid with a landing page and no download, so a scientist may never open it.
- **A new entry in a list starts closed.** After pressing the plus, its fields show only when the
  new row is clicked.
- **The form's own red marks.** A red count beside a list, and "is a required property" under the
  landing page on an empty form, appear before anything has been checked, and may disagree with
  the report.
- **Variables.** The report recommends linking a variable to a concept; the form has no field for
  that.
- **A place** can be a name and a box of four numbers. There is no map.
- **After submitting, nothing visibly happens to the record.** It is not published and does not
  appear in the catalogue. A scientist may reasonably ask where it went.

## Writing up

One page, against the table in the plan.

| Result of three sessions | Decision |
|---|---|
| 3 of 3 submit a valid record unaided within 20 minutes | Proceed with JSON Forms for all editing. |
| 2 of 3 | Fix what blocked the third, retest with two new people. |
| 1 or 0 of 3 | Build the scientist form by hand for `CoreDiscovery`; keep JSON Forms for data managers only. |

A session passes only if all three hold:

- **Valid:** the record was submitted, which the server allows only when nothing must be fixed.
- **Unaided:** the "Help given" list on the observation sheet is empty.
- **Within 20 minutes** on the clock, not counting time stopped for a fault in the prototype.

```
Scientist sessions: result

Date(s):                     Prototype version (commit on main):

            | Valid | Unaided | Minutes | Passed
Session 1   |       |         |         |
Session 2   |       |         |         |
Session 3   |       |         |         |

Result: _ of 3.    Decision, from the table:

What stopped or slowed people, most serious first (each with how many of the three it affected):
1.
2.
3.

What worked without comment:

What they had no place to say:

Faults in the prototype during the sessions:

What to change before anyone else uses it:
```

Record a session that failed for a reason outside the form (a fault in the prototype, a dataset
the scientist could not remember) as void, not as a fail, and say so. Three sessions is a small
number: report what happened in each, and do not turn it into percentages.
