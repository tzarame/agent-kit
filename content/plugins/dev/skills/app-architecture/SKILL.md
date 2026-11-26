---
name: app-architecture
description: The structure inside one application - modules, components, layers, boundaries, dependencies, the data model, public interfaces, who owns code and data. Use when starting an application, adding a large part to it, reorganizing its code, splitting, merging or moving components, or when one change touches many modules.
---

Follow the structure the application already has. Change it only when the task needs it, and say so.
Give each module one job and a small interface. Dependencies go one way: no circles.
Keep the logic apart from input and output (the screen, the network, the database), so each can be tested and replaced alone.

Where the boundaries go:
- Group code by one shared purpose, so each module needs little from the others. Avoid catch-all helper modules.
- Draw components along business workflows and user actions, not along data tables or vague names like Manager.
- Split a component whose responsibility needs several "and"s, or whose parts need different reliability levels.
- Keep tight coupling inside a module. Between modules, keep direct calls rare and use narrow, visible contracts.
- Redraw a boundary when modules talk too much, instead of adding more calls.
- Count how many modules one typical change touches. If it is many, the boundaries are wrong.

Who owns what:
- Give each behavior exactly one owner. Extract shared logic instead of copying it.
- Give each fact one owning module or service. Treat copies and caches as derived.
- Give each module its own data unless sharing is a deliberate choice. One shared database couples every change.
- Share code only when it is well abstracted and stable. Volatile domain code is cheaper to copy than to share.

A changed public interface, data format or database schema breaks code and data you do not see: other services, clients, old records.
Find who uses a thing before you change it. Reorganize in small steps, each of which still works and can be reverted.
