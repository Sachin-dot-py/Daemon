# Daemon

# Inspiration

We started with something simple: an RC car.

It could move forward, backward, turn left, turn right. That was it. It worked. We were happy.

Then we thought — what if we add a robotic arm?

So we bought one. From a completely different manufacturer. Different firmware. Different assumptions. Different everything.

And that’s when we hit the wall.

You don’t just plug in an arm and magically get a smarter robot. You end up rewriting firmware, changing control logic, debugging serial communication, fixing timing issues, and basically rebuilding half your system just to make two pieces of hardware cooperate.

Every time you add something new, you start over.

That didn’t feel right.

The AI was capable. The hardware worked. But the AI had no idea what its own body was.

So we asked a simple question:

What if the robot could figure that out on its own?

That’s why we built **Daemon**.

---

# The Core Idea

Daemon lets AI learn what its body parts are and how to use them.

You attach a new arm.

Instead of hardcoding support for it, the AI begins exploring:

“Oh, this rotates.”  
“This joint moves up and down.”  
“This closes.”  
“If I close this around something, I can grab it.”

It builds an internal model of what it can do.

Not because we wrote special case logic.

But because it tried, failed, adjusted, and learned.

---

# How It Works (In Real Life)

Let’s say you tell the robot:

> “Go pick up that banana.”

The AI understands the goal.

But it doesn’t automatically know how to use the arm perfectly.

So it experiments.

It drives forward. Too far. Adjusts.  
It lowers the arm. Misses. Tries again.  
It grips too early. Drops it. Learns.

You point your laptop camera at the robot while it practices. That visual feedback becomes the signal that tells it whether it succeeded or failed.

It keeps iterating.

And here’s the part we love:

You can leave. Go grab dinner.

Come back a few hours later.

Now the robot can pick up the banana.

You didn’t write new motor logic.  
You didn’t rewrite the firmware stack.  
You didn’t manually calibrate every joint.

It learned how to use its new arm.

---

# What Makes This Different

Normally, hardware integration is rigid. Static. Painful.

With Daemon:

Adding a new part isn’t a rewrite.  
It’s a capability to be discovered.

We separate the system into layers:

The AI decides what it wants to do.  
Daemon handles safe execution and learning.  
The hardware simply exposes what it can physically do.

That separation is what makes adaptation possible.

---

# Why This Matters

Right now, robots are custom-built systems. Every upgrade is engineering overhead. Time and money are lost!

If AI can understand its own body, hardware becomes modular.

You could swap wheels for legs.  
Add a gripper.  
Attach a drill.  

And instead of rewriting everything, the intelligence adapts.

We didn’t just build a robot that moves.

We built a system where AI learns how to move.

---

# How We Did It

1. **Firmware to DAEMON interface (`daemon-cli`)**  
   Manufacturers annotate existing firmware APIs, and `daemon-cli` generates a standardized DAEMON manifest + runtime wrapper.

2. **Node discovery and capability exposure**  
   Each hardware module (base, arm, camera, etc.) exposes its commands and telemetry as a DAEMON node over serial/TCP.

3. **Natural-language control from `desktop-app`**  
   Users connect devices and type goals in plain English. They do not need to manually map commands to components.

4. **Planning + orchestration**  
   The planner converts user intent into structured action steps, and `orchestrator` validates, routes, and executes those steps across one or more nodes safely.

5. **Closed-loop autonomy (`autonomy-engine`)**  
   The autonomy loop uses live camera frames plus an OpenAI-based critic to run an execute → evaluate → adjust cycle.  
   It updates control parameters between attempts and stops when success is stable (for example, 2 consecutive successful iterations).

6. **End result**  
   DAEMON turns heterogeneous firmware and hardware into one AI-operable system, enabling multi-device behavior without custom per-device orchestration logic.
