#!/usr/bin/env python
"""Minimal GUI for midi_to_ngpc (Tkinter)."""

import os
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog

THEMES = {
    "dark": {
        "bg": "#1e1e1e",
        "panel": "#252526",
        "fg": "#e6e6e6",
        "muted": "#b0b0b0",
        "entry_bg": "#2d2d30",
        "button_bg": "#3a3a3a",
        "accent": "#7bd88f",
        "warning": "#e6b422",
        "error": "#e86a6a",
        "tooltip_bg": "#202225",
        "tooltip_fg": "#e6e6e6",
        "tooltip_border": "#3a3a3a",
    },
    "light": {
        "bg": "#f4f4f4",
        "panel": "#ffffff",
        "fg": "#1f1f1f",
        "muted": "#5a5a5a",
        "entry_bg": "#ffffff",
        "button_bg": "#e6e6e6",
        "accent": "#2f8f5b",
        "warning": "#c28a1b",
        "error": "#b84b4b",
        "tooltip_bg": "#f0f0f0",
        "tooltip_fg": "#1f1f1f",
        "tooltip_border": "#c0c0c0",
    },
}

INSTRUMENT_PRESETS = {
    "None": "",
    "Arcade": "instrument_map_arcade.json",
    "Action": "instrument_map_action.json",
    "Adventure": "instrument_map_adventure.json",
    "RPG": "instrument_map_rpg.json",
    "Punk": "instrument_map_punk.json",
    "Clean": "instrument_map_clean.json",
    "Chip": "instrument_map_chip.json",
    "Chiptune": "instrument_map_chiptune.json",
    "Pop": "instrument_map_pop.json",
    "Rock": "instrument_map_rock.json",
    "HipHop": "instrument_map_hiphop.json",
    "EDM": "instrument_map_edm.json",
    "DnB": "instrument_map_dnb.json",
    "LoFi": "instrument_map_lofi.json",
    "Custom": None,
}


class Tooltip:
    def __init__(self, widget: tk.Widget, text, palette_getter=None) -> None:
        self.widget = widget
        self.text = text
        self.palette_getter = palette_getter
        self._tip = None
        self._after = None
        widget.bind("<Enter>", self._schedule)
        widget.bind("<Leave>", self._hide)
        widget.bind("<ButtonPress>", self._hide)

    def _schedule(self, _event=None) -> None:
        self._after = self.widget.after(500, self._show)

    def _show(self) -> None:
        if self._tip:
            return
        text = self.text() if callable(self.text) else self.text
        if not text:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        if self.palette_getter:
            bg, fg, border = self.palette_getter()
        else:
            bg, fg, border = "#202225", "#e6e6e6", "#3a3a3a"
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            self._tip,
            text=text,
            justify="left",
            background=bg,
            foreground=fg,
            relief="solid",
            borderwidth=1,
            font=("Segoe UI", 9),
            padx=6,
            pady=4,
            wraplength=380,
            highlightbackground=border,
        )
        label.pack()

    def _hide(self, _event=None) -> None:
        if self._after:
            self.widget.after_cancel(self._after)
            self._after = None
        if self._tip:
            self._tip.destroy()
            self._tip = None


def _default_output_path(input_path: str) -> str:
    if not input_path:
        return ""
    base, _ = os.path.splitext(input_path)
    return base + ".asm"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("midi_to_ngpc")
        self.geometry("880x680")

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.use_velocity_var = tk.BooleanVar(value=False)
        self.c_array_var = tk.BooleanVar(value=False)
        self.poly_var = tk.BooleanVar(value=False)
        self.split_voices_var = tk.BooleanVar(value=True)
        self.preempt_var = tk.BooleanVar(value=True)
        self.grid_var = tk.StringVar(value="48")
        self.fps_var = tk.StringVar(value="60")
        self.channels_var = tk.StringVar(value="2")
        self.noise_channel_var = tk.StringVar(value="9")
        self.profile_var = tk.StringVar(value="Custom")
        self.density_mode_var = tk.StringVar(value="auto")
        self.density_bias_var = tk.StringVar(value="6")
        self.density_bass_var = tk.StringVar(value="2")
        self.auto_status_var = tk.StringVar(value="")
        self.drum_mode_var = tk.StringVar(value="snk")
        self.pitchbend_var = tk.BooleanVar(value=True)
        self.pitchbend_range_var = tk.StringVar(value="2")
        self.cc_volume_var = tk.BooleanVar(value=False)
        self.sustain_var = tk.BooleanVar(value=True)
        self.base_midi_var = tk.StringVar(value="45")
        self.loop_start_frame_var = tk.StringVar(value="")
        self.loop_start_tick_var = tk.StringVar(value="")
        self.auto_loop_rest_var = tk.StringVar(value="")
        self.loop_reset_fx_var = tk.BooleanVar(value=False)
        self.trace_output_var = tk.StringVar(value="")
        self.instrument_map_var = tk.StringVar(value="")
        self.instrument_preset_var = tk.StringVar(value="None")
        self.emit_opcodes_var = tk.BooleanVar(value=False)
        self.force_tone_var = tk.BooleanVar(value=False)
        self.force_noise_var = tk.BooleanVar(value=False)
        self.show_advanced_var = tk.BooleanVar(value=False)
        self.dark_mode_var = tk.BooleanVar(value=True)
        self.tooltip_lang_var = tk.StringVar(value="EN")
        self._option_menus = []

        self._build_ui()

    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 6}
        tt = self._tt

        row = 0
        lbl_profile = tk.Label(self, text="Profile")
        lbl_profile.grid(row=row, column=0, sticky="w", **pad)
        profile_menu = self._option_menu(
            self,
            self.profile_var,
            ["Custom", "Mono", "Mono Timing", "Poly2", "Poly3", "Arranged 3+Noise", "SNK Drums", "Fidelity"],
            command=self._apply_profile,
        )
        profile_menu.grid(row=row, column=1, sticky="w", **pad)
        tt(lbl_profile, "Quick presets tuned for NGPC music exports.", "Presets rapides optimises pour la NGPC.")
        tt(profile_menu, "Select a preset or keep Custom to tweak values.", "Choisissez un preset ou gardez Custom.")

        chk_dark = tk.Checkbutton(self, text="Dark mode", variable=self.dark_mode_var, command=self._apply_theme)
        chk_dark.grid(row=row, column=2, sticky="w", **pad)
        tt(chk_dark, "Dark theme (better for eyes at night).", "Theme sombre (plus confortable).")

        lbl_lang = tk.Label(self, text="Tooltips")
        lbl_lang.grid(row=row, column=3, sticky="e", **pad)
        lang_menu = self._option_menu(self, self.tooltip_lang_var, ["EN", "FR"])
        lang_menu.grid(row=row, column=4, sticky="w", **pad)
        tt(lbl_lang, "Tooltip language.", "Langue des info-bulles.")

        row += 1
        lbl_input = tk.Label(self, text="Input MIDI")
        lbl_input.grid(row=row, column=0, sticky="w", **pad)
        ent_input = tk.Entry(self, textvariable=self.input_var, width=60)
        ent_input.grid(row=row, column=1, **pad)
        btn_input = tk.Button(self, text="Browse", command=self._browse_input)
        btn_input.grid(row=row, column=2, **pad)
        tt(lbl_input, "MIDI file to convert (Type 0 or Type 1).", "Fichier MIDI a convertir (Type 0 ou 1).")
        tt(ent_input, "Path to the input .mid file.", "Chemin du fichier .mid.")
        tt(btn_input, "Pick a MIDI file.", "Choisir un fichier MIDI.")

        row += 1
        lbl_output = tk.Label(self, text="Output File")
        lbl_output.grid(row=row, column=0, sticky="w", **pad)
        ent_output = tk.Entry(self, textvariable=self.output_var, width=60)
        ent_output.grid(row=row, column=1, **pad)
        btn_output = tk.Button(self, text="Browse", command=self._browse_output)
        btn_output.grid(row=row, column=2, **pad)
        tt(lbl_output, "Destination file (.asm or .c).", "Fichier de sortie (.asm ou .c).")
        tt(ent_output, "Output file path. Extension controls ASM vs C.", "Chemin de sortie. L'extension choisit ASM/C.")
        tt(btn_output, "Choose where to save the export.", "Choisir ou enregistrer l'export.")

        row += 1
        basic = tk.LabelFrame(self, text="Basic")
        basic.grid(row=row, column=0, columnspan=3, sticky="ew", **pad)

        chk_c = tk.Checkbutton(basic, text="Export C arrays", variable=self.c_array_var, command=self._sync_output_ext)
        chk_c.grid(row=0, column=0, sticky="w", padx=6, pady=4)
        tt(chk_c, "Emit const unsigned char arrays instead of ASM .db.", "Sortie en tableaux C plutot qu'en ASM.")

        chk_poly = tk.Checkbutton(basic, text="Poly output", variable=self.poly_var)
        chk_poly.grid(row=0, column=1, sticky="w", padx=6, pady=4)
        tt(chk_poly, "Enable poly export. Produces BGM_CHx instead of mono.", "Active la polyphonie (BGM_CHx).")

        lbl_ch = tk.Label(basic, text="Voices")
        lbl_ch.grid(row=1, column=0, sticky="w", padx=6, pady=4)
        ent_ch = tk.Entry(basic, textvariable=self.channels_var, width=6)
        ent_ch.grid(row=1, column=1, sticky="w", padx=6, pady=4)
        tt(lbl_ch, "Max voices for poly export. 3=tones, 4=tones+noise.", "Voix max. 3=tons, 4=tons+noise.")

        lbl_noise = tk.Label(basic, text="Drum ch (noise)")
        lbl_noise.grid(row=1, column=2, sticky="w", padx=6, pady=4)
        ent_noise = tk.Entry(basic, textvariable=self.noise_channel_var, width=6)
        ent_noise.grid(row=1, column=3, sticky="w", padx=6, pady=4)
        tt(lbl_noise, "MIDI channel used as noise (GM drums = 9).", "Canal MIDI pour le bruit (GM drums = 9).")

        lbl_drum = tk.Label(basic, text="Drum mode")
        lbl_drum.grid(row=2, column=0, sticky="w", padx=6, pady=4)
        drum_menu = self._option_menu(basic, self.drum_mode_var, ["off", "snk"])
        drum_menu.grid(row=2, column=1, sticky="w", padx=6, pady=4)
        tt(lbl_drum, "How to render channel 10 drums.", "Conversion des drums (canal 10).")
        tt(drum_menu, "snk: kick->tone, snare->noise, hats short.", "snk: kick->tone, snare->noise, hats courts.")

        chk_vel = tk.Checkbutton(basic, text="Use velocity (attn stream)", variable=self.use_velocity_var)
        chk_vel.grid(row=2, column=2, columnspan=2, sticky="w", padx=6, pady=4)
        tt(chk_vel, "Generate BGM_MONO_ATTN from velocity (0=loudest, 15=silent).",
           "Genere BGM_MONO_ATTN depuis la velocite (0=fort,15=silence).")

        lbl_preset = tk.Label(basic, text="Instrument preset")
        lbl_preset.grid(row=3, column=0, sticky="w", padx=6, pady=4)
        preset_menu = self._option_menu(
            basic,
            self.instrument_preset_var,
            [
                "None",
                "Arcade",
                "Action",
                "Adventure",
                "RPG",
                "Punk",
                "Clean",
                "Chip",
                "Chiptune",
                "Pop",
                "Rock",
                "HipHop",
                "EDM",
                "DnB",
                "LoFi",
                "Custom",
            ],
            command=self._apply_instrument_preset,
        )
        preset_menu.grid(row=3, column=1, sticky="w", padx=6, pady=4)
        tt(lbl_preset, "Select a preset FX map (sets instrument map path).",
           "Choisir un preset FX (configure instrument_map).")
        tt(preset_menu, "Presets auto-enable FX opcodes.",
           "Les presets activent automatiquement les opcodes.")

        row += 1
        timing = tk.LabelFrame(self, text="Timing")
        timing.grid(row=row, column=0, columnspan=3, sticky="ew", **pad)
        lbl_grid = tk.Label(timing, text="Grid (ticks)")
        lbl_grid.grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ent_grid = tk.Entry(timing, textvariable=self.grid_var, width=10)
        ent_grid.grid(row=0, column=1, sticky="w", padx=6, pady=4)
        lbl_fps = tk.Label(timing, text="FPS")
        lbl_fps.grid(row=0, column=2, sticky="w", padx=6, pady=4)
        ent_fps = tk.Entry(timing, textvariable=self.fps_var, width=6)
        ent_fps.grid(row=0, column=3, sticky="w", padx=6, pady=4)
        tt(lbl_grid, "Quantization grid in MIDI ticks. Larger = simpler rhythm.",
           "Grille de quantif. Plus grand = rythme plus simple.")
        tt(ent_grid, "Common values: 48, 96 (TPB=480).", "Valeurs courantes: 48, 96 (TPB=480).")
        tt(lbl_fps, "Target playback FPS for durations.", "FPS cible pour les durees.")
        tt(ent_fps, "Usually 60 for NGPC VBlank scheduling.", "En general 60 (VBlank NGPC).")

        row += 1
        chk_adv = tk.Checkbutton(
            self,
            text="Show advanced options",
            variable=self.show_advanced_var,
            command=self._toggle_advanced,
        )
        chk_adv.grid(row=row, column=0, sticky="w", **pad)
        tt(chk_adv, "Show advanced expert options.", "Afficher les options avancees.")

        row += 1
        self.advanced_frame = tk.LabelFrame(self, text="Advanced")
        self.advanced_frame.grid(row=row, column=0, columnspan=3, sticky="ew", **pad)

        adv = self.advanced_frame
        chk_split = tk.Checkbutton(adv, text="Split voices (poly)", variable=self.split_voices_var)
        chk_split.grid(row=0, column=0, sticky="w", padx=6, pady=4)
        tt(chk_split, "Greedy voice split (use only for unarranged MIDI).",
           "Repartit les voix (utile si le MIDI n'est pas arrange).")

        chk_preempt = tk.Checkbutton(adv, text="Allow preempt", variable=self.preempt_var)
        chk_preempt.grid(row=0, column=1, sticky="w", padx=6, pady=4)
        tt(chk_preempt, "Let stronger notes replace weaker ones during overlap.",
           "Les notes fortes remplacent les faibles si chevauchement.")

        lbl_bend = tk.Label(adv, text="Pitch bend")
        lbl_bend.grid(row=1, column=0, sticky="w", padx=6, pady=4)
        chk_bend = tk.Checkbutton(adv, text="Enable", variable=self.pitchbend_var)
        chk_bend.grid(row=1, column=1, sticky="w", padx=6, pady=4)
        lbl_bend_range = tk.Label(adv, text="Range")
        lbl_bend_range.grid(row=1, column=2, sticky="w", padx=6, pady=4)
        ent_bend_range = tk.Entry(adv, textvariable=self.pitchbend_range_var, width=6)
        ent_bend_range.grid(row=1, column=3, sticky="w", padx=6, pady=4)
        tt(lbl_bend, "Apply pitch bend events from the MIDI.", "Appliquer les pitch bends MIDI.")
        tt(ent_bend_range, "Semitone range. Default 2.", "Amplitude en demi-tons. Defaut 2.")

        lbl_cc = tk.Label(adv, text="CC volume")
        lbl_cc.grid(row=2, column=0, sticky="w", padx=6, pady=4)
        chk_cc = tk.Checkbutton(adv, text="Use CC7/CC11", variable=self.cc_volume_var)
        chk_cc.grid(row=2, column=1, sticky="w", padx=6, pady=4)
        lbl_sus = tk.Label(adv, text="Sustain")
        lbl_sus.grid(row=2, column=2, sticky="w", padx=6, pady=4)
        chk_sus = tk.Checkbutton(adv, text="Enable", variable=self.sustain_var)
        chk_sus.grid(row=2, column=3, sticky="w", padx=6, pady=4)
        tt(lbl_cc, "Apply CC7/CC11 to velocity (if present).", "Appliquer CC7/CC11 a la velocite.")
        tt(chk_sus, "Handle CC64 sustain pedal.", "Gerer la pedale sustain (CC64).")

        lbl_density = tk.Label(adv, text="Density")
        lbl_density.grid(row=3, column=0, sticky="w", padx=6, pady=4)
        density_menu = self._option_menu(adv, self.density_mode_var, ["auto", "off", "soft", "hard"])
        density_menu.grid(row=3, column=1, sticky="w", padx=6, pady=4)
        lbl_bias = tk.Label(adv, text="Bias")
        lbl_bias.grid(row=3, column=2, sticky="w", padx=6, pady=4)
        ent_bias = tk.Entry(adv, textvariable=self.density_bias_var, width=6)
        ent_bias.grid(row=3, column=3, sticky="w", padx=6, pady=4)
        lbl_bass = tk.Label(adv, text="Bass")
        lbl_bass.grid(row=3, column=4, sticky="w", padx=6, pady=4)
        ent_bass = tk.Entry(adv, textvariable=self.density_bass_var, width=6)
        ent_bass.grid(row=3, column=5, sticky="w", padx=6, pady=4)
        tt(lbl_density, "Chord thinning when MIDI is too dense.", "Reduction d'accords si trop dense.")

        lbl_base = tk.Label(adv, text="Base MIDI")
        lbl_base.grid(row=4, column=0, sticky="w", padx=6, pady=4)
        ent_base = tk.Entry(adv, textvariable=self.base_midi_var, width=6)
        ent_base.grid(row=4, column=1, sticky="w", padx=6, pady=4)
        tt(lbl_base, "Base note for NOTE_TABLE index 0 (default 45 = A2).",
           "Note de base pour l'index 0 (defaut 45 = A2).")
        tt(ent_base, "Same as base note (default 45).", "Idem, valeur de base (45 par defaut).")

        lbl_loop_frame = tk.Label(adv, text="Loop start (frame)")
        lbl_loop_frame.grid(row=4, column=2, sticky="w", padx=6, pady=4)
        ent_loop_frame = tk.Entry(adv, textvariable=self.loop_start_frame_var, width=8)
        ent_loop_frame.grid(row=4, column=3, sticky="w", padx=6, pady=4)
        lbl_loop_tick = tk.Label(adv, text="Loop start (tick)")
        lbl_loop_tick.grid(row=4, column=4, sticky="w", padx=6, pady=4)
        ent_loop_tick = tk.Entry(adv, textvariable=self.loop_start_tick_var, width=8)
        ent_loop_tick.grid(row=4, column=5, sticky="w", padx=6, pady=4)
        tt(lbl_loop_frame, "Explicit loop position in frames.", "Position de boucle en frames.")
        tt(lbl_loop_tick, "Explicit loop position in MIDI ticks.", "Position de boucle en ticks MIDI.")
        tt(ent_loop_frame, "Frame number where the loop should start.", "Frame ou commence la boucle.")
        tt(ent_loop_tick, "Tick number where the loop should start.", "Tick ou commence la boucle.")

        lbl_auto_loop = tk.Label(adv, text="Auto loop rest")
        lbl_auto_loop.grid(row=5, column=0, sticky="w", padx=6, pady=4)
        ent_auto_loop = tk.Entry(adv, textvariable=self.auto_loop_rest_var, width=8)
        ent_auto_loop.grid(row=5, column=1, sticky="w", padx=6, pady=4)
        chk_loop_reset = tk.Checkbutton(adv, text="Loop reset FX", variable=self.loop_reset_fx_var)
        chk_loop_reset.grid(row=5, column=2, sticky="w", padx=6, pady=4)
        tt(lbl_auto_loop, "Auto-pick loop at common silence (0.5 = 50% song).",
           "Auto-choix boucle sur silence commun (0.5 = 50%).")
        tt(ent_auto_loop, "Leave empty to disable auto loop.", "Laisser vide pour desactiver.")
        tt(chk_loop_reset, "Re-emit instrument FX at loop start (needs opcodes).",
           "Re-envoie les FX a la boucle (opcodes requis).")

        lbl_inst = tk.Label(adv, text="Instrument map")
        lbl_inst.grid(row=6, column=0, sticky="w", padx=6, pady=4)
        ent_inst = tk.Entry(adv, textvariable=self.instrument_map_var, width=40)
        ent_inst.grid(row=6, column=1, columnspan=2, sticky="w", padx=6, pady=4)
        btn_inst = tk.Button(adv, text="Browse", command=self._browse_instrument_map)
        btn_inst.grid(row=6, column=3, sticky="w", padx=6, pady=4)
        btn_inst_open = tk.Button(adv, text="Open", command=self._open_instrument_map)
        btn_inst_open.grid(row=6, column=4, sticky="w", padx=6, pady=4)
        chk_opcodes = tk.Checkbutton(adv, text="Emit FX opcodes", variable=self.emit_opcodes_var)
        chk_opcodes.grid(row=6, column=5, sticky="w", padx=6, pady=4)
        tt(lbl_inst, "JSON map: Program Change -> env/vib/sweep.", "JSON: Program Change -> env/vib/sweep.")
        tt(chk_opcodes, "Enable opcodes when instrument map is provided.",
           "Activer les opcodes si un instrument_map est fourni.")
        tt(ent_inst, "Path to instrument_map.json.", "Chemin vers instrument_map.json.")
        tt(btn_inst, "Pick a JSON instrument map.", "Choisir un instrument map JSON.")
        tt(btn_inst_open, "Open the current instrument map file.", "Ouvrir le fichier instrument_map.")

        lbl_trace = tk.Label(adv, text="Trace output")
        lbl_trace.grid(row=7, column=0, sticky="w", padx=6, pady=4)
        ent_trace = tk.Entry(adv, textvariable=self.trace_output_var, width=40)
        ent_trace.grid(row=7, column=1, columnspan=2, sticky="w", padx=6, pady=4)
        btn_trace = tk.Button(adv, text="Browse", command=self._browse_trace_output)
        btn_trace.grid(row=7, column=3, sticky="w", padx=6, pady=4)
        tt(lbl_trace, "Optional trace log for debugging decisions.", "Trace optionnel pour debug.")
        tt(ent_trace, "Path to a .txt file for trace output.", "Chemin du fichier trace .txt.")
        tt(btn_trace, "Choose a trace output file.", "Choisir un fichier trace.")

        chk_force_tone = tk.Checkbutton(adv, text="Force tone streams", variable=self.force_tone_var)
        chk_force_tone.grid(row=8, column=0, sticky="w", padx=6, pady=4)
        chk_force_noise = tk.Checkbutton(adv, text="Force noise stream", variable=self.force_noise_var)
        chk_force_noise.grid(row=8, column=1, sticky="w", padx=6, pady=4)
        tt(chk_force_tone, "Emit empty BGM_CHx even if no notes.", "Force BGM_CHx meme vides.")
        tt(chk_force_noise, "Emit empty BGM_CHN even if no drums.", "Force BGM_CHN meme vide.")

        if not self.show_advanced_var.get():
            self.advanced_frame.grid_remove()

        row += 1
        btn_auto = tk.Button(self, text="Auto settings", command=self._auto_settings)
        btn_auto.grid(row=row, column=1, sticky="w", **pad)
        tt(btn_auto, "Analyze MIDI and suggest grid/channels/poly settings.",
           "Analyse le MIDI et propose des reglages.")

        btn_run = tk.Button(self, text="Start conversion", command=self._run)
        btn_run.grid(row=row, column=2, sticky="w", **pad)
        tt(btn_run, "Run conversion with the selected options.", "Lancer la conversion.")

        lbl_status = tk.Label(self, textvariable=self.auto_status_var, fg="#c9c9c9")
        lbl_status.grid(row=row, column=0, sticky="w", **pad)

        row += 1
        self.console = tk.Text(self, height=10, width=80)
        self.console.grid(row=row, column=0, columnspan=3, sticky="nsew", **pad)
        tt(self.console, "Conversion log and warnings.", "Log de conversion et alertes.")

        self.grid_rowconfigure(row, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self._apply_theme()

    def _apply_profile(self, _value: str) -> None:
        name = self.profile_var.get()
        if name == "Custom":
            return
        if name == "Mono":
            self.poly_var.set(False)
            self.channels_var.set("1")
            self.grid_var.set("48")
            self.density_mode_var.set("off")
            self.drum_mode_var.set("off")
            self.force_tone_var.set(False)
            self.force_noise_var.set(False)
        elif name == "Mono Timing":
            self.poly_var.set(False)
            self.channels_var.set("1")
            self.grid_var.set("1")
            self.density_mode_var.set("off")
            self.drum_mode_var.set("off")
            self.force_tone_var.set(False)
            self.force_noise_var.set(False)
        elif name == "Poly2":
            self.poly_var.set(True)
            self.channels_var.set("2")
            self.split_voices_var.set(True)
            self.preempt_var.set(True)
            self.grid_var.set("48")
            self.density_mode_var.set("auto")
            self.drum_mode_var.set("off")
            self.force_tone_var.set(True)
            self.force_noise_var.set(False)
        elif name == "Poly3":
            self.poly_var.set(True)
            self.channels_var.set("3")
            self.split_voices_var.set(True)
            self.preempt_var.set(True)
            self.grid_var.set("48")
            self.density_mode_var.set("auto")
            self.drum_mode_var.set("off")
            self.force_tone_var.set(True)
            self.force_noise_var.set(False)
        elif name == "Arranged 3+Noise":
            self.poly_var.set(True)
            self.channels_var.set("4")
            self.noise_channel_var.set("9")
            self.split_voices_var.set(False)
            self.preempt_var.set(False)
            self.grid_var.set("48")
            self.density_mode_var.set("off")
            self.drum_mode_var.set("off")
            self.force_tone_var.set(True)
            self.force_noise_var.set(True)
        elif name == "SNK Drums":
            self.poly_var.set(True)
            self.channels_var.set("4")
            self.noise_channel_var.set("9")
            self.split_voices_var.set(False)
            self.preempt_var.set(False)
            self.grid_var.set("48")
            self.density_mode_var.set("off")
            self.density_bias_var.set("6")
            self.density_bass_var.set("2")
            self.drum_mode_var.set("snk")
            self.force_tone_var.set(True)
            self.force_noise_var.set(True)
        elif name == "Fidelity":
            self.poly_var.set(True)
            self.channels_var.set("4")
            self.noise_channel_var.set("9")
            self.split_voices_var.set(False)
            self.preempt_var.set(False)
            self.grid_var.set("1")
            self.density_mode_var.set("off")
            self.drum_mode_var.set("off")
            self.pitchbend_var.set(True)
            self.pitchbend_range_var.set("2")
            self.cc_volume_var.set(True)
            self.sustain_var.set(True)
            self.force_tone_var.set(True)
            self.force_noise_var.set(True)

    def _browse_input(self) -> None:
        path = filedialog.askopenfilename(
            title="Select MIDI file",
            filetypes=[("MIDI files", "*.mid *.midi"), ("All files", "*.*")],
        )
        if path:
            self.input_var.set(path)
            if not self.output_var.get():
                self.output_var.set(_default_output_path(path))

    def _browse_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Select output file",
            defaultextension=".asm",
            filetypes=[("ASM files", "*.asm"), ("C files", "*.c"), ("All files", "*.*")],
        )
        if path:
            self.output_var.set(path)
            self._sync_c_array_from_output()

    def _browse_instrument_map(self) -> None:
        path = filedialog.askopenfilename(
            title="Select instrument map",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            self.instrument_map_var.set(path)
            self.instrument_preset_var.set("Custom")
            self.emit_opcodes_var.set(True)

    def _open_instrument_map(self) -> None:
        path = self.instrument_map_var.get().strip()
        if not path:
            self._log("Error: no instrument map selected.")
            return
        if not os.path.exists(path):
            self._log("Error: instrument map not found.")
            return
        try:
            os.startfile(path)
        except Exception as exc:
            self._log(f"Error: failed to open map ({exc}).")

    def _browse_trace_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Select trace output",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if path:
            self.trace_output_var.set(path)

    def _apply_instrument_preset(self, _value: str) -> None:
        name = self.instrument_preset_var.get()
        if name == "Custom":
            return
        if name == "None":
            self.instrument_map_var.set("")
            self.emit_opcodes_var.set(False)
            return
        filename = INSTRUMENT_PRESETS.get(name)
        if not filename:
            return
        base = os.path.dirname(__file__)
        path = os.path.join(base, "instrument_maps", filename)
        self.instrument_map_var.set(path)
        self.emit_opcodes_var.set(True)

    def _toggle_advanced(self) -> None:
        if self.show_advanced_var.get():
            self.advanced_frame.grid()
        else:
            self.advanced_frame.grid_remove()

    def _sync_output_ext(self) -> None:
        path = self.output_var.get().strip()
        if not path:
            return
        base, ext = os.path.splitext(path)
        want_c = self.c_array_var.get()
        if want_c and ext.lower() != ".c":
            self.output_var.set(base + ".c")
        if (not want_c) and ext.lower() == ".c":
            self.output_var.set(base + ".asm")

    def _option_menu(self, parent, variable, values, command=None):
        menu = tk.OptionMenu(parent, variable, *values, command=command)
        self._option_menus.append(menu)
        return menu

    def _get_theme(self) -> dict:
        return THEMES["dark"] if self.dark_mode_var.get() else THEMES["light"]

    def _tooltip_palette(self):
        t = self._get_theme()
        return t["tooltip_bg"], t["tooltip_fg"], t["tooltip_border"]

    def _tt(self, widget, en: str, fr: str) -> None:
        def _text():
            return fr if self.tooltip_lang_var.get() == "FR" else en

        Tooltip(widget, _text, palette_getter=self._tooltip_palette)

    def _iter_widgets(self, root):
        stack = [root]
        while stack:
            w = stack.pop()
            yield w
            try:
                stack.extend(w.winfo_children())
            except Exception:
                pass

    def _apply_theme(self) -> None:
        t = self._get_theme()
        self.configure(bg=t["bg"])
        for w in self._iter_widgets(self):
            self._apply_theme_to_widget(w, t)
        self.console.configure(
            bg=t["entry_bg"],
            fg=t["fg"],
            insertbackground=t["fg"],
        )
        self.console.tag_configure("warning", foreground=t["warning"])
        self.console.tag_configure("error", foreground=t["error"])
        self.console.tag_configure("ok", foreground=t["accent"])
        for menu in self._option_menus:
            try:
                menu.configure(
                    bg=t["button_bg"],
                    fg=t["fg"],
                    activebackground=t["panel"],
                    activeforeground=t["fg"],
                )
                menu["menu"].configure(
                    bg=t["panel"],
                    fg=t["fg"],
                    activebackground=t["button_bg"],
                    activeforeground=t["fg"],
                )
            except Exception:
                pass

    def _apply_theme_to_widget(self, widget, t):
        try:
            if isinstance(widget, tk.LabelFrame):
                widget.configure(bg=t["panel"], fg=t["fg"])
            elif isinstance(widget, tk.Frame):
                bg = t["panel"] if isinstance(widget.master, tk.LabelFrame) else t["bg"]
                widget.configure(bg=bg)
            elif isinstance(widget, tk.Label):
                bg = t["panel"] if isinstance(widget.master, tk.LabelFrame) else t["bg"]
                widget.configure(bg=bg, fg=t["fg"])
            elif isinstance(widget, tk.Entry):
                widget.configure(
                    bg=t["entry_bg"],
                    fg=t["fg"],
                    insertbackground=t["fg"],
                    highlightbackground=t["panel"],
                    highlightcolor=t["panel"],
                )
            elif isinstance(widget, tk.Text):
                widget.configure(
                    bg=t["entry_bg"],
                    fg=t["fg"],
                    insertbackground=t["fg"],
                )
            elif isinstance(widget, tk.Checkbutton):
                bg = t["panel"] if isinstance(widget.master, tk.LabelFrame) else t["bg"]
                widget.configure(
                    bg=bg,
                    fg=t["fg"],
                    activebackground=bg,
                    activeforeground=t["fg"],
                    selectcolor=bg,
                )
            elif isinstance(widget, (tk.Button, tk.Menubutton)):
                widget.configure(
                    bg=t["button_bg"],
                    fg=t["fg"],
                    activebackground=t["panel"],
                    activeforeground=t["fg"],
                    selectcolor=t["panel"],
                )
        except Exception:
            pass

    def _sync_c_array_from_output(self) -> None:
        path = self.output_var.get().strip()
        if not path:
            return
        _, ext = os.path.splitext(path)
        self.c_array_var.set(ext.lower() == ".c")

    def _log(self, msg: str) -> None:
        tag = None
        if msg.startswith("Warning:"):
            tag = "warning"
        elif msg.startswith("Error:") or msg.startswith("Exception:"):
            tag = "error"
        elif msg == "Done.":
            tag = "ok"
        self.console.insert("end", msg + "\n", tag)
        self.console.see("end")

    def _auto_settings(self) -> None:
        path = self.input_var.get().strip()
        if not path:
            self._log("Error: select a MIDI file first.")
            return
        try:
            import mido
        except Exception as exc:
            self._log(f"Error: mido not available ({exc}).")
            return

        try:
            mid = mido.MidiFile(path)
        except Exception as exc:
            self._log(f"Error: failed to read MIDI ({exc}).")
            return

        channels = set()
        note_events = []
        tempo_count = 0
        cc_volume = 0
        cc_expression = 0
        cc_sustain = 0
        abs_tick = 0
        for msg in mido.merge_tracks(mid.tracks):
            abs_tick += msg.time
            if msg.type == "set_tempo":
                tempo_count += 1
            if msg.type == "control_change":
                if msg.control == 7:
                    cc_volume += 1
                elif msg.control == 11:
                    cc_expression += 1
                elif msg.control == 64:
                    cc_sustain += 1
            if msg.type in ("note_on", "note_off"):
                ch = getattr(msg, "channel", 0)
                channels.add(ch)
                note = msg.note
                vel = getattr(msg, "velocity", 0)
                is_on = msg.type == "note_on" and vel > 0
                note_events.append((abs_tick, is_on, ch, note))

        # Estimate max polyphony (simple overlap count).
        active = set()
        max_poly = 0
        for tick, is_on, ch, note in note_events:
            key = (ch, note)
            if is_on:
                active.add(key)
            else:
                active.discard(key)
            if len(active) > max_poly:
                max_poly = len(active)

        tpb = mid.ticks_per_beat or 480
        if tpb >= 960:
            grid = 96
        elif tpb == 480:
            grid = 48
        elif tpb % 96 == 0:
            grid = 96
        else:
            grid = 48

        use_noise = 9 in channels
        tone_channels = min(3, len([c for c in channels if c != 9]))
        if tone_channels <= 0:
            tone_channels = 1

        arranged = tone_channels <= 3
        self.poly_var.set(tone_channels > 1 or use_noise)
        self.channels_var.set(str(4 if use_noise and tone_channels >= 3 else max(1, tone_channels)))
        self.noise_channel_var.set("9")
        self.split_voices_var.set(False if arranged else True)
        self.preempt_var.set(False if arranged else True)
        self.grid_var.set(str(grid))
        self.density_mode_var.set("off" if arranged else "auto")
        self.density_bias_var.set("6")
        self.density_bass_var.set("2")
        self.drum_mode_var.set("off" if use_noise else "off")
        self.cc_volume_var.set(cc_volume > 0 or cc_expression > 0)
        self.sustain_var.set(cc_sustain > 0)
        self.force_tone_var.set(bool(self.poly_var.get()))
        self.force_noise_var.set(bool(use_noise))

        status = f"Auto: tpb={tpb}, max_poly={max_poly}, ch={sorted(channels)}"
        self.auto_status_var.set(status)
        self.profile_var.set("Custom")
        self._log("Done.")

    def _run(self) -> None:
        input_path = self.input_var.get().strip()
        output_path = self.output_var.get().strip()

        if not input_path or not output_path:
            self._log("Error: input and output are required.")
            return

        cmd = [sys.executable, os.path.join(os.path.dirname(__file__), "midi_to_ngpc.py")]
        cmd += [input_path, output_path]

        if self.use_velocity_var.get():
            cmd.append("--use-velocity")
        output_ext = os.path.splitext(output_path)[1].lower()
        if self.c_array_var.get() or output_ext == ".c":
            cmd.append("--c-array")
        if self.poly_var.get():
            cmd.append("--poly")
            channels = self.channels_var.get().strip()
            if channels:
                cmd += ["--channels", channels]
            if self.split_voices_var.get():
                cmd.append("--split-voices")
            else:
                cmd.append("--no-split-voices")
            if self.preempt_var.get():
                cmd.append("--preempt")
            else:
                cmd.append("--no-preempt")
            noise_ch = self.noise_channel_var.get().strip()
            if noise_ch:
                cmd += ["--noise-channel", noise_ch]
            drum_mode = self.drum_mode_var.get().strip()
            if drum_mode:
                cmd += ["--drum-mode", drum_mode]
            density_mode = self.density_mode_var.get().strip()
            if density_mode:
                cmd += ["--density-mode", density_mode]
            density_bias = self.density_bias_var.get().strip()
            if density_bias:
                cmd += ["--density-bias", density_bias]
            density_bass = self.density_bass_var.get().strip()
            if density_bass:
                cmd += ["--density-bass", density_bass]

        if self.pitchbend_var.get():
            bend_range = self.pitchbend_range_var.get().strip()
            if bend_range:
                cmd += ["--pitchbend-range", bend_range]
        else:
            cmd.append("--no-pitchbend")

        if self.cc_volume_var.get():
            cmd.append("--use-cc-volume")
        if not self.sustain_var.get():
            cmd.append("--no-sustain")

        grid = self.grid_var.get().strip()
        if grid:
            cmd += ["--grid", grid]
        fps = self.fps_var.get().strip()
        if fps:
            cmd += ["--fps", fps]
        base_midi = self.base_midi_var.get().strip()
        if base_midi:
            cmd += ["--base-midi", base_midi]
        loop_frame = self.loop_start_frame_var.get().strip()
        if loop_frame:
            cmd += ["--loop-start-frame", loop_frame]
        loop_tick = self.loop_start_tick_var.get().strip()
        if loop_tick:
            cmd += ["--loop-start-tick", loop_tick]
        auto_loop = self.auto_loop_rest_var.get().strip()
        if auto_loop:
            cmd += ["--auto-loop-rest", auto_loop]

        inst_map = self.instrument_map_var.get().strip()
        if inst_map:
            cmd += ["--instrument-map", inst_map]
            if self.emit_opcodes_var.get():
                cmd.append("--opcodes")
            else:
                cmd.append("--no-opcodes")
        elif self.emit_opcodes_var.get():
            self._log("Error: enable opcodes requires an instrument map.")
            return
        if self.loop_reset_fx_var.get():
            if not inst_map or not self.emit_opcodes_var.get():
                self._log("Error: loop reset FX requires instrument map + opcodes.")
                return
            cmd.append("--loop-reset-fx")

        if self.force_tone_var.get():
            cmd.append("--force-tone-streams")
        if self.force_noise_var.get():
            cmd.append("--force-noise-stream")
        trace_out = self.trace_output_var.get().strip()
        if trace_out:
            cmd += ["--trace-output", trace_out]

        self._log("Running: " + " ".join(cmd))

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.stdout:
                self._log(result.stdout.strip())
            if result.stderr:
                self._log(result.stderr.strip())
            if result.returncode == 0:
                self._log("Done.")
            else:
                self._log(f"Failed (code {result.returncode}).")
        except Exception as exc:
            self._log(f"Exception: {exc}")


def main() -> int:
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
