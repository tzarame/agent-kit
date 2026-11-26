---
name: system-design
description: How the parts of a system fit together - the architecture style (monolith, modular monolith, layered, pipeline, plug-in, event-driven, services), services, databases, queues, caches, outside APIs, an LLM as a part, load, failures, quality targets (speed, scale, availability, ease of change). Use when planning or changing how parts talk to each other, where data lives, how the system grows or fails, when choosing the shape of a system or splitting it, or when requirements set quality targets.
---

Start from the numbers: the load, the size of the data, what must never be lost, how long the system may be down.
Draw the parts and the path of the data before you choose a technology.
Take the simplest design that meets the numbers: each new part is one more thing to run and to break. For each part, say what happens when it fails.

The quality targets:
- Turn each goal into a measurable target with a number. Split a composite goal into its parts and measure each one.
- Keep the driving targets to a few, about three, chosen by the stakeholders. Each one adds cost and complexity.
- Look for needs the requirements leave unstated, such as traffic bursts, outages of outside services, data growth. Make them explicit.
- Define each target once for the whole project, so everyone uses the same meaning.
- Before committing, predict how improving one target changes the others, and estimate the cost of building and running it.
- Measure the slowest requests and the maximums, not only the averages. A rare slow request hides in an average.
- Scope each target to the unit that is deployed on its own, not to the whole system.
- Keep the architecture cheap to change. An early guess should be cheap to fix.

The style:
- Default to one monolith. Distribute a system only when its parts clearly need different quality targets. When the direction is unclear, start with a modular monolith and split later, only if needed.
- Choose the style from the quality targets and the domain facts, never from fashion. Name it before coding, so it does not emerge by accident.
- Start with synchronous calls. Add asynchronous messaging only where a concrete need appears, such as absorbing bursts or decoupling.
- Keep each business workflow, with its strong internal coupling, in one unit. Do not split it across services.
- Size services by business capability, not by the smallest possible piece. Count the network calls one user request makes.
- Let layers talk only through contracts. A request that skips a layer must be a documented choice.
- Publish events as facts that already happened. Send commands to one named handler.
- Use request-based reads where the answer must be deterministic, and events where scale requires them.
- Migrate between styles one piece at a time, behind a switch that can be turned back.

An AI model as a part of the system:
- Hide each model call behind an interface, so one model can be swapped for another without rewriting the caller.
- Keep the model's guardrails and its evaluations outside the caller, where they can be changed separately.
- Log samples of inputs and outputs, and measure them, so two models can be compared on the same cases.
- Keep the model out of decisions where the answer must be correct and repeatable; use code, rules or tests there.

A design is cheap to write and expensive to undo: it decides where data can be lost, what goes down together, and what the user pays every month.
Say the risks and the cost of each option in plain words. Do not present a guess as a fact: say what you measured and what you assumed.
