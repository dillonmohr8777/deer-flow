# Thread Runs replay endpoints

Moved out of `app/gateway/AGENTS.md` (Thread Runs row) to keep it under its byte budget. Nothing was dropped.

`POST /regenerate/prepare` - prepare clean input + checkpoint metadata for regenerating the latest completed or interrupted assistant answer, treating a protocol-valid hidden `human_input_response` as confirmed replay input while rejecting other hidden/control humans, preserving its hidden/correlation metadata, and carrying the latest non-empty thread title in graph input so resuming an older checkpoint cannot roll back a later manual rename (#4457); `POST /edit-regenerate/prepare` - prepare a checkpoint replay from the latest editable human turn with a replacement user message and edit replay metadata; it carries the current thread title the same way, but only when the replay base already has one, since pinning the title on an untitled base would keep a name generated from the prompt the edit just replaced;
