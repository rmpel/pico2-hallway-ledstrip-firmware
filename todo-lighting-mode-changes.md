# Lighting mode changes

## Current

Current situation with the PHYSICAL BUTTONS is 

- ON: turn on light in 'temporary' mode (resume schedule when next event)
- OFF: turn off light in 'temporary' mode (resume schedule when next event)
- AUTO: go to schedule mode
- ALT+AUTO: go rainbow

## New modes

- Add a Christmas light mode where LEDS are a repeated pattern of Red, Green, Blue, Yellow (maybe more in future) and have the color tones adjusted to be the softer 1980s colors.
- This mode is in multiple variants;
	- static
	- changing by flipping the order and shifting one every tick - this way it is not a "walking progression" but a clear "replace this with that". Also; color changes are a smooth fade. Duration of the fade and static phases are configuratble.
	- leave options for more

## Button changes

- ALT-AUTO no longer starts Rainbow but cycles through all new modes
	- 1st press; Rainbow
	- next press; Christmas static
	- next press; Christmas changing
	- next press; Christmas next if there were any
	- next press; Next lighting mode if there were any
	- next press when all have passed; back to Rainbow
