---
name: testing
description: Quality assurance - testing a product as a user would, finding defects and reporting them. Use when the task is to test a product, a page or a flow, find what does not work, and report it.
---

Decide before starting what is tested and what "works" means: the flow, the user, the expected result.
Test the behaviour a user sees, by running the thing, not by reading the code.
Cover the edge states: empty, error, no access, wrong input, and a phone's width for a page.
A defect report says where it is, the steps to repeat it, what was expected, what happened, and a screenshot or the output. One defect per report. Report where the user or the project asks; with no place named, in your answer.
A defect filed on GitHub: the defects of one page or one flow are one issue with a list; look for an existing issue first and add to it instead of opening a copy; `gh issue create` opens one. A screenshot cannot be uploaded to an issue from the command line: commit it to a private repository kept for that (do not create one), and link it.
Say plainly what was tested and what was not. Do not fix the code yourself: a defect is reported, not changed.

Tests run against real data or a live service can destroy or change it, and a report posted in public can show what should stay private. Test in a test environment, keep test data apart from real data, and ask before anything that changes real data or sends a message to real users.
