# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk  # Themed widgets
from tkinter import simpledialog, messagebox, filedialog, scrolledtext
import pyautogui
import time
import os
import json
import sys
from PIL import Image, ImageTk
import cv2
import numpy as np
import platform
import uuid
import shutil
import threading
import queue
import traceback

# --- Configuration ---
BASE_FOLDER = "pc_macrorify_data"
MACROS_FOLDER = os.path.join(BASE_FOLDER, "macros")
SCREENSHOTS_FOLDER = os.path.join(BASE_FOLDER, "screenshots")
# --- Default Action Settings ---
DEFAULT_CONFIDENCE = 0.8
DEFAULT_DELAY_BEFORE = 0.2
DEFAULT_DELAY_AFTER = 0.2
DEFAULT_CLICK_DURATION = 0.05
DEFAULT_REPEAT_COUNT = 1
DEFAULT_REPEAT_DELAY = 0.1
DEFAULT_SEARCH_TIMEOUT = 5.0
DEFAULT_SEARCH_INTERVAL = 0.5
DEFAULT_SCROLL_DIRECTION = 'down'
DEFAULT_SCROLL_AMOUNT = 3
DEFAULT_TYPE_INTERVAL = 0.01


# --- Core Automation Logic (Unchanged from previous version) ---

def ensure_dirs():
    os.makedirs(MACROS_FOLDER, exist_ok=True)
    os.makedirs(SCREENSHOTS_FOLDER, exist_ok=True)

def _locate_image_once(template_filename, confidence=DEFAULT_CONFIDENCE):
    template_path = os.path.join(SCREENSHOTS_FOLDER, template_filename)
    if not os.path.exists(template_path):
        app.log(f"Error: Template image not found: '{template_path}'")
        return None
    try:
        return pyautogui.locateOnScreen(template_path, confidence=confidence, grayscale=True)
    except pyautogui.ImageNotFoundException: return None
    except Exception as e:
        app.log(f"Error during locateOnScreen for '{template_filename}': {e}")
        if sys.platform == 'darwin': app.log("macOS: Ensure Screen Recording permission.")
        return None

def perform_click(x, y, delay_before=DEFAULT_DELAY_BEFORE, delay_after=DEFAULT_DELAY_AFTER, duration=DEFAULT_CLICK_DURATION, button='left', repeat_count=DEFAULT_REPEAT_COUNT, repeat_delay=DEFAULT_REPEAT_DELAY):
    try:
        repeat_info = f"[Repeat: {repeat_count}x, RepDelay: {repeat_delay}s]" if repeat_count > 1 else ""
        app.log(f"Clicking at ({x:.0f}, {y:.0f}) {repeat_info} [Btn: {button}, Dur: {duration}s, Delay B/A: {delay_before}s/{delay_after}s]")
        app.root.update_idletasks()
        time.sleep(delay_before)
        for i in range(repeat_count):
            if app.stop_macro_flag: app.log("Stop signal during repeat click."); return False
            pyautogui.click(x=x, y=y, duration=duration, button=button)
            app.log(f"  -> Click {i+1}/{repeat_count} performed.")
            app.root.update_idletasks()
            if i < repeat_count - 1:
                start_sleep = time.time()
                while time.time() - start_sleep < repeat_delay:
                     if app.stop_macro_flag: break
                     time.sleep(0.05)
                if app.stop_macro_flag: return False
        time.sleep(delay_after)
        return True
    except Exception as e: app.log(f"Error during click sequence: {e}"); return False

def perform_scroll(direction=DEFAULT_SCROLL_DIRECTION, amount=DEFAULT_SCROLL_AMOUNT, delay_before=DEFAULT_DELAY_BEFORE, delay_after=DEFAULT_DELAY_AFTER):
    try:
        scroll_amount = int(amount) if direction == 'down' else -int(amount)
        app.log(f"Scrolling {direction} by {amount} units [Delay B/A: {delay_before}s/{delay_after}s]")
        app.root.update_idletasks(); time.sleep(delay_before)
        if app.stop_macro_flag: return False
        pyautogui.scroll(scroll_amount)
        time.sleep(delay_after); return True
    except Exception as e: app.log(f"Error during scroll: {e}"); return False

def perform_type(text_to_type="", interval=DEFAULT_TYPE_INTERVAL, delay_before=DEFAULT_DELAY_BEFORE, delay_after=DEFAULT_DELAY_AFTER):
    try:
        logged_text = text_to_type[:30] + "..." if len(text_to_type) > 30 else text_to_type
        app.log(f"Typing text: '{logged_text}' [Interval: {interval}s, Delay B/A: {delay_before}s/{delay_after}s]")
        app.root.update_idletasks(); time.sleep(delay_before)
        if app.stop_macro_flag: return False
        pyautogui.write(text_to_type, interval=interval)
        time.sleep(delay_after); return True
    except Exception as e: app.log(f"Error during typing: {e}"); return False

def debug_visualize(found_box, click_x, click_y):
    app.log("Debug: Visualizing detection...")
    app.root.update_idletasks()
    try:
        screenshot = pyautogui.screenshot(); screenshot_cv = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        marker_pos = None
        if click_x is not None and click_y is not None: marker_pos = (int(click_x), int(click_y))
        if found_box:
            tl = (found_box.left, found_box.top); br = (found_box.left + found_box.width, found_box.top + found_box.height)
            cv2.rectangle(screenshot_cv, tl, br, (0, 255, 0), 2)
        if marker_pos: cv2.drawMarker(screenshot_cv, marker_pos, (0, 0, 255), markerType=cv2.MARKER_CROSS, markerSize=20, thickness=2)
        cv2.imshow("Debug Visualization - Press ESC in window to close", screenshot_cv); cv2.waitKey(1)
        msg_parts = ["Debug image window shown."]
        if found_box: msg_parts.append(f"Found Box: {found_box}")
        if marker_pos: msg_parts.append(f"Action Target: ({marker_pos[0]}, {marker_pos[1]})")
        msg_parts.append("\nPress OK to perform the action, Cancel to skip.")
        proceed = messagebox.askokcancel("Debug Visualization", "\n".join(msg_parts), parent=app.root)
        cv2.destroyAllWindows(); return proceed
    except Exception as e:
        app.log(f"Error during debug visualization: {e}"); cv2.destroyAllWindows()
        messagebox.showerror("Debug Error", f"Could not show debug window:\n{e}", parent=app.root); return False

# --- Tkinter Application Class ---

class MacroApp:
    # --- __init__ (Layout mostly unchanged) ---
    def __init__(self, root):
        self.root = root
        self.root.title("PC Auto Macro")
        self.macros = []; self.current_macro_name = None; self.current_macro_actions = []
        self.selected_macro_index = -1; self.selected_step_index = -1; self.temp_crop_info = {}
        self.macro_running = False; self.stop_macro_flag = False; self.log_queue = queue.Queue()
        self.style = ttk.Style()
        try: self.style.theme_use('clam')
        except tk.TclError:
            try: self.style.theme_use('default')
            except tk.TclError: print("Warning: Could not set Tk theme.")

        self.top_frame = ttk.Frame(root, padding="10"); self.top_frame.pack(side=tk.TOP, fill=tk.X)
        self.middle_frame = ttk.Frame(root, padding="10"); self.middle_frame.pack(side=tk.TOP, fill=tk.BOTH) # No expand here
        self.bottom_frame = ttk.Frame(root, padding="10"); self.bottom_frame.pack(side=tk.BOTTOM, fill=tk.X)

        # Top Frame Widgets
        self.macro_list_label = ttk.Label(self.top_frame, text="Available Macros:"); self.macro_list_label.pack(side=tk.LEFT, padx=(0, 10))
        self.macro_listbox = tk.Listbox(self.top_frame, height=5, exportselection=False); self.macro_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True); self.macro_listbox.bind('<<ListboxSelect>>', self.on_macro_select)
        self.macro_scrollbar = ttk.Scrollbar(self.top_frame, orient=tk.VERTICAL, command=self.macro_listbox.yview); self.macro_scrollbar.pack(side=tk.LEFT, fill=tk.Y); self.macro_listbox.config(yscrollcommand=self.macro_scrollbar.set)
        self.controls_frame = ttk.Frame(self.top_frame, padding=(10, 0)); self.controls_frame.pack(side=tk.LEFT)
        self.btn_new = ttk.Button(self.controls_frame, text="New", command=self.new_macro); self.btn_new.grid(row=0, column=0, pady=2, sticky="ew")
        self.btn_edit = ttk.Button(self.controls_frame, text="Edit Macro", command=self.edit_macro, state=tk.DISABLED); self.btn_edit.grid(row=1, column=0, pady=2, sticky="ew")
        self.btn_run = ttk.Button(self.controls_frame, text="Run", command=self.run_selected_macro, state=tk.DISABLED); self.btn_run.grid(row=2, column=0, pady=2, sticky="ew")
        self.btn_run_debug = ttk.Button(self.controls_frame, text="Run Debug", command=lambda: self.run_selected_macro(debug=True), state=tk.DISABLED); self.btn_run_debug.grid(row=3, column=0, pady=2, sticky="ew")
        self.btn_delete_macro = ttk.Button(self.controls_frame, text="Delete Macro", command=self.delete_macro, state=tk.DISABLED); self.btn_delete_macro.grid(row=4, column=0, pady=2, sticky="ew")
        self.btn_crop_utility = ttk.Button(self.controls_frame, text="Crop Utility", command=self.open_crop_utility); self.btn_crop_utility.grid(row=5, column=0, pady=5, sticky="ew")

        # Middle Frame (Editor) Widgets
        self.editor_frame = ttk.Frame(self.middle_frame) # Packed on demand
        self.editor_label = ttk.Label(self.editor_frame, text="Editing Macro:", font=('Helvetica', 12, 'bold')); self.editor_label.pack(side=tk.TOP, pady=5)
        self.steps_list_frame = ttk.Frame(self.editor_frame); self.steps_list_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,10))
        self.steps_list_label = ttk.Label(self.steps_list_frame, text="Steps:"); self.steps_list_label.pack(side=tk.TOP, anchor='w')
        self.steps_listbox = tk.Listbox(self.steps_list_frame, height=15, exportselection=False); self.steps_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); self.steps_listbox.bind('<<ListboxSelect>>', self.on_step_select)
        self.steps_scrollbar = ttk.Scrollbar(self.steps_list_frame, orient=tk.VERTICAL, command=self.steps_listbox.yview); self.steps_scrollbar.pack(side=tk.LEFT, fill=tk.Y); self.steps_listbox.config(yscrollcommand=self.steps_scrollbar.set)
        self.step_controls_frame = ttk.Frame(self.editor_frame); self.step_controls_frame.pack(side=tk.LEFT, anchor='n')
        self.btn_add_step = ttk.Button(self.step_controls_frame, text="Add Step", command=self.add_step); self.btn_add_step.grid(row=0, column=0, pady=3, sticky="ew")
        self.btn_edit_step = ttk.Button(self.step_controls_frame, text="Edit Step", command=self.edit_step, state=tk.DISABLED); self.btn_edit_step.grid(row=1, column=0, pady=3, sticky="ew")
        self.btn_delete_step = ttk.Button(self.step_controls_frame, text="Delete Step", command=self.delete_step, state=tk.DISABLED); self.btn_delete_step.grid(row=2, column=0, pady=3, sticky="ew")
        self.btn_move_up = ttk.Button(self.step_controls_frame, text="Move Up", command=self.move_step_up, state=tk.DISABLED); self.btn_move_up.grid(row=3, column=0, pady=3, sticky="ew")
        self.btn_move_down = ttk.Button(self.step_controls_frame, text="Move Down", command=self.move_step_down, state=tk.DISABLED); self.btn_move_down.grid(row=4, column=0, pady=3, sticky="ew")
        self.btn_save_macro = ttk.Button(self.step_controls_frame, text="Save Macro", command=self.save_edited_macro); self.btn_save_macro.grid(row=5, column=0, pady=10, sticky="ew")
        self.btn_cancel_edit = ttk.Button(self.step_controls_frame, text="Cancel Edit", command=self.cancel_edit_macro); self.btn_cancel_edit.grid(row=6, column=0, pady=3, sticky="ew")

        # Bottom Frame Widgets
        self.log_label = ttk.Label(self.bottom_frame, text="Log / Status:"); self.log_label.pack(side=tk.TOP, anchor='w')
        self.log_area = scrolledtext.ScrolledText(self.bottom_frame, height=8, wrap=tk.WORD, state=tk.DISABLED); self.log_area.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.btn_stop_macro = ttk.Button(self.bottom_frame, text="STOP MACRO", command=self.stop_macro_signal)

        # Init
        ensure_dirs(); self.refresh_macro_list(); self.log("Application started.")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing); self.process_log_queue()
        self.root.minsize(width=550, height=450) # Set a minimum size

    # --- Logging (Unchanged) ---
    def log(self, message): self.log_queue.put(message)
    def process_log_queue(self):
        try:
            while True:
                message = self.log_queue.get_nowait()
                self.log_area.config(state=tk.NORMAL)
                self.log_area.insert(tk.END, f"{time.strftime('%H:%M:%S')} - {message}\n")
                self.log_area.see(tk.END); self.log_area.config(state=tk.DISABLED)
                self.root.update_idletasks()
        except queue.Empty: pass
        finally: self.root.after(100, self.process_log_queue)

    # --- Macro List Handling (Unchanged) ---
    def refresh_macro_list(self):
        self.log("Refreshing macro list...") # Log refresh action
        self.macro_listbox.delete(0, tk.END); self.macros = []
        try:
            files = sorted([f for f in os.listdir(MACROS_FOLDER) if f.endswith(".json")])
            for f in files: macro_name = f[:-5]; self.macros.append(macro_name); self.macro_listbox.insert(tk.END, macro_name)
        except Exception as e: self.log(f"Error listing macros: {e}"); messagebox.showerror("Error", f"Could not read macros: {e}")
        self.update_macro_buttons()
    def on_macro_select(self, event=None):
        sel = self.macro_listbox.curselection()
        self.selected_macro_index = sel[0] if sel else -1
        self.current_macro_name = self.macros[self.selected_macro_index] if self.selected_macro_index != -1 else None
        self.update_macro_buttons()
    def update_macro_buttons(self):
        is_selected = self.selected_macro_index != -1
        edit_run_state = tk.NORMAL if is_selected and not self.macro_running else tk.DISABLED
        general_state = tk.NORMAL if not self.macro_running and not self.editor_frame.winfo_ismapped() else tk.DISABLED
        self.btn_edit.config(state=edit_run_state)
        self.btn_run.config(state=edit_run_state)
        self.btn_run_debug.config(state=edit_run_state)
        self.btn_delete_macro.config(state=edit_run_state)
        self.btn_new.config(state=general_state)
        # Crop Utility should be enabled unless macro is running
        self.btn_crop_utility.config(state=tk.NORMAL if not self.macro_running else tk.DISABLED)

    # --- Macro CRUD (Unchanged) ---
    def new_macro(self):
        name = simpledialog.askstring("New Macro", "Enter macro name:", parent=self.root)
        if name and name.strip():
            name = name.strip(); filename = f"{name}.json"; filepath = os.path.join(MACROS_FOLDER, filename)
            if os.path.exists(filepath): messagebox.showerror("Error", f"Macro '{name}' exists.", parent=self.root); return
            if any(c in name for c in r'<>:"/\|?*'): messagebox.showerror("Error", "Invalid characters in name.", parent=self.root); return
            self.current_macro_name = name; self.current_macro_actions = []
            self.show_editor(); self.log(f"Creating new macro '{name}'.")
        elif name is not None: messagebox.showwarning("Warning", "Name cannot be empty.", parent=self.root)
    def edit_macro(self):
        if not self.current_macro_name: return
        actions = self._load_macro_actions(self.current_macro_name)
        if actions is not None: self.current_macro_actions = actions; self.show_editor(); self.log(f"Editing '{self.current_macro_name}'.")
        else: messagebox.showerror("Error", f"Failed to load '{self.current_macro_name}'.", parent=self.root)
    def delete_macro(self):
        if not self.current_macro_name: return
        if messagebox.askyesno("Confirm Delete", f"Delete '{self.current_macro_name}'?", parent=self.root):
            filename = f"{self.current_macro_name}.json"; filepath = os.path.join(MACROS_FOLDER, filename)
            try:
                os.remove(filepath); self.log(f"Macro '{self.current_macro_name}' deleted.")
                self.current_macro_name = None; self.selected_macro_index = -1; self.refresh_macro_list()
            except Exception as e: self.log(f"Error deleting '{self.current_macro_name}': {e}"); messagebox.showerror("Error", f"Could not delete: {e}", parent=self.root)
    def _load_macro_actions(self, name):
        filepath = os.path.join(MACROS_FOLDER, f"{name}.json")
        try:
            with open(filepath, 'r', encoding='utf-8') as f: actions = json.load(f)
            if not isinstance(actions, list): raise json.JSONDecodeError("Not a JSON list", "", 0)
            self.log(f"Loaded '{name}'."); return actions
        except FileNotFoundError: self.log(f"Error: Not found '{filepath}'."); return None
        except json.JSONDecodeError as e: self.log(f"Error: Invalid JSON '{filepath}': {e}"); return None
        except Exception as e: self.log(f"Error loading '{name}': {e}"); return None
    def _save_macro_actions(self, name, actions):
         filepath = os.path.join(MACROS_FOLDER, f"{name}.json")
         try:
             with open(filepath, 'w', encoding='utf-8') as f: json.dump(actions, f, indent=4)
             self.log(f"Saved '{name}'."); return True
         except Exception as e: self.log(f"Error saving '{name}': {e}"); messagebox.showerror("Save Error", f"Could not save: {e}", parent=self.root); return False

    # --- Macro Editor UI ---
    def show_editor(self):
        self.editor_label.config(text=f"Editing Macro: {self.current_macro_name}")
        self.refresh_steps_listbox()
        self.editor_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True) # Expand editor
        self.update_macro_buttons() # Update general button states
        self.macro_listbox.config(state=tk.DISABLED)

    # --- Updated hide_editor ---
    def hide_editor(self):
        self.editor_frame.pack_forget()
        self.current_macro_actions = []
        # Macro list refresh is handled by save_edited_macro or cancel_edit_macro
        self.macro_listbox.config(state=tk.NORMAL)
        self.update_macro_buttons() # Update general button states
        # Reset geometry to allow shrinking
        self.root.update_idletasks() # Process pending events
        self.root.geometry("") # Request natural size

    # --- Updated save_edited_macro ---
    def save_edited_macro(self):
        macro_to_select = self.current_macro_name
        if self._save_macro_actions(self.current_macro_name, self.current_macro_actions):
            self.log(f"Saved changes to '{macro_to_select}'.")
            self.hide_editor()
            self.refresh_macro_list() # Refresh list *after* hiding editor and saving
            try:
                 saved_index = self.macros.index(macro_to_select) # Find new macro in refreshed list
                 if saved_index != -1 and saved_index < self.macro_listbox.size():
                    self.macro_listbox.selection_clear(0, tk.END)
                    self.macro_listbox.selection_set(saved_index)
                    self.on_macro_select() # Trigger selection update
            except ValueError: # Macro name wasn't found (shouldn't happen if save succeeded)
                 self.current_macro_name = None
                 self.on_macro_select()

    # --- Updated cancel_edit_macro ---
    def cancel_edit_macro(self):
        if messagebox.askyesno("Confirm Cancel", "Discard changes?", parent=self.root):
            self.log("Editing cancelled."); self.hide_editor()
            # Re-read selection state after hiding editor
            sel = self.macro_listbox.curselection()
            self.selected_macro_index = sel[0] if sel else -1
            self.current_macro_name = self.macros[self.selected_macro_index] if self.selected_macro_index != -1 else None
            self.update_macro_buttons() # Ensure buttons reflect selection

    # --- Step List Handling (refresh_steps_listbox updated) ---
    def refresh_steps_listbox(self):
        last_selected = self.selected_step_index
        self.steps_listbox.delete(0, tk.END); self.selected_step_index = -1
        for i, step in enumerate(self.current_macro_actions):
            action_type = step.get('action', 'Unknown'); details = []
            if action_type == 'find_and_click':
                 details.append(f"Image='{step.get('template', '?')}'")
                 if float(step.get('confidence', DEFAULT_CONFIDENCE)) != DEFAULT_CONFIDENCE: details.append(f"Conf={step.get('confidence')}")
                 st = float(step.get('search_timeout', DEFAULT_SEARCH_TIMEOUT)); si = float(step.get('search_interval', DEFAULT_SEARCH_INTERVAL))
                 if st != DEFAULT_SEARCH_TIMEOUT: details.append(f"Timeout={'inf' if st == -1 else f'{st}s'}")
                 if si != DEFAULT_SEARCH_INTERVAL: details.append(f"Interval={si}s")
                 # Click specific for find_and_click
                 if step.get('offset_x', 0) != 0 or step.get('offset_y', 0) != 0: details.append(f"Offset=({step.get('offset_x', 0)},{step.get('offset_y', 0)})")
            elif action_type == 'click_at': details.append(f"Pos=({step.get('x', '?')},{step.get('y', '?')})")
            elif action_type == 'delay': details.append(f"Duration={step.get('duration', '?')}s")
            elif action_type == 'scroll': details.append(f"Dir={step.get('direction', '?')}"); details.append(f"Amount={step.get('amount', '?')}")
            elif action_type == 'type_text': txt = step.get('text', ''); details.append(f"Text='{txt[:15] + '...' if len(txt) > 15 else txt}'"); details.append(f"Interval={step.get('interval', '?')}s")

            is_click = action_type in ['find_and_click', 'click_at']
            has_delays = action_type not in ['delay'] # Actions that can have pre/post delays

            if is_click:
                rc = int(step.get('repeat_count', 1)); rd = float(step.get('repeat_delay', 0.1))
                if rc > 1: details.append(f"Repeat={rc}x"); details.append(f"RepDelay={rd}s")
                if step.get('button', 'left') != 'left': details.append(f"Btn={step.get('button')}")
                if float(step.get('duration', DEFAULT_CLICK_DURATION)) != DEFAULT_CLICK_DURATION: details.append(f"Hold={step.get('duration')}s")

            if has_delays:
                 if float(step.get('delay_before', DEFAULT_DELAY_BEFORE)) != DEFAULT_DELAY_BEFORE: details.append(f"PreDelay={step.get('delay_before')}s")
                 if float(step.get('delay_after', DEFAULT_DELAY_AFTER)) != DEFAULT_DELAY_AFTER: details.append(f"PostDelay={step.get('delay_after')}s")

            display_text = f"{i + 1}. {action_type}: {', '.join(details)}"
            self.steps_listbox.insert(tk.END, display_text)

        if 0 <= last_selected < self.steps_listbox.size(): self.steps_listbox.selection_set(last_selected); self.selected_step_index = last_selected
        self.update_step_buttons()
    # --- on_step_select, update_step_buttons (Unchanged) ---
    def on_step_select(self, event=None):
        sel = self.steps_listbox.curselection(); self.selected_step_index = sel[0] if sel else -1; self.update_step_buttons()
    def update_step_buttons(self):
        is_selected = self.selected_step_index != -1; state = tk.NORMAL if is_selected else tk.DISABLED
        self.btn_edit_step.config(state=state); self.btn_delete_step.config(state=state)
        self.btn_move_up.config(state=tk.NORMAL if is_selected and self.selected_step_index > 0 else tk.DISABLED)
        self.btn_move_down.config(state=tk.NORMAL if is_selected and self.selected_step_index < len(self.current_macro_actions) - 1 else tk.DISABLED)

    # --- Step CRUD (Unchanged) ---
    def add_step(self):
        dialog = AddStepDialog(self.root, title="Add New Step")
        if dialog.result:
            new_action = dialog.result; insert_pos = self.selected_step_index + 1 if self.selected_step_index != -1 else len(self.current_macro_actions)
            self.current_macro_actions.insert(insert_pos, new_action); self.log(f"Added: {new_action['action']}")
            self.refresh_steps_listbox();
            if insert_pos < self.steps_listbox.size(): self.steps_listbox.selection_set(insert_pos); self.on_step_select()
    def edit_step(self):
        if self.selected_step_index == -1: return
        current_action = self.current_macro_actions[self.selected_step_index].copy()
        dialog = EditStepDialog(self.root, action_data=current_action, title="Edit Step Details")
        if dialog.result:
            updated_action = dialog.result; self.current_macro_actions[self.selected_step_index] = updated_action
            self.log(f"Edited step {self.selected_step_index + 1}"); self.refresh_steps_listbox();
            if self.selected_step_index < self.steps_listbox.size(): self.steps_listbox.selection_set(self.selected_step_index); self.on_step_select()
    def delete_step(self):
        if self.selected_step_index == -1: return
        if messagebox.askyesno("Confirm Delete", "Delete step?", parent=self.editor_frame):
            deleted = self.current_macro_actions.pop(self.selected_step_index); self.log(f"Deleted step {self.selected_step_index + 1}: {deleted['action']}")
            self.refresh_steps_listbox(); new_sel = min(self.selected_step_index, len(self.current_macro_actions) - 1)
            if new_sel >= 0: self.steps_listbox.selection_set(new_sel); self.on_step_select()
    def move_step_up(self):
        if self.selected_step_index <= 0: return
        idx = self.selected_step_index; action = self.current_macro_actions.pop(idx); self.current_macro_actions.insert(idx - 1, action)
        self.log(f"Moved step {idx + 1} up."); self.refresh_steps_listbox(); self.steps_listbox.selection_set(idx - 1); self.on_step_select()
    def move_step_down(self):
        if self.selected_step_index == -1 or self.selected_step_index >= len(self.current_macro_actions) - 1: return
        idx = self.selected_step_index; action = self.current_macro_actions.pop(idx); self.current_macro_actions.insert(idx + 1, action)
        self.log(f"Moved step {idx + 1} down."); self.refresh_steps_listbox(); self.steps_listbox.selection_set(idx + 1); self.on_step_select()

    # --- Crop Utility (Unchanged) ---
    def open_crop_utility(self):
        self.log("Crop: Taking screenshot..."); self.root.update_idletasks(); fs_path = self._take_temp_screenshot()
        if not fs_path: return
        fn = simpledialog.askstring("Crop", "Final filename:", parent=self.root)
        if not fn or not fn.strip(): self.log("Crop cancelled."); self._cleanup_temp_file(fs_path); return
        fn = fn.strip(); fn += ".png" if not fn.lower().endswith(('.png', '.jpg', '.jpeg')) else ""
        t_uuid = uuid.uuid4(); t_fn = f"crop_temp_{t_uuid}.png"; t_path = os.path.join(SCREENSHOTS_FOLDER, t_fn); final_path = os.path.join(SCREENSHOTS_FOLDER, fn)
        self.temp_crop_info = {"fullscreen_path": fs_path, "temp_save_path": t_path, "temp_save_filename": t_fn, "final_output_path": final_path, "desired_filename": fn}
        use_sf = platform.system() == "Windows"; editor_ok = False
        if use_sf:
            try: self.log(f"Opening '{os.path.basename(fs_path)}'..."); os.startfile(fs_path); editor_ok = True
            except Exception as e: self.log(f"Err opening editor: {e}"); use_sf = False
        instr = ("1. Crop area.\n2. 'Save As' with temp name below (use Copy!).\n"
                 f"   Save Location: '{SCREENSHOTS_FOLDER}'\n3. Close editor.\n4. Click Confirm.")
        if not use_sf and not editor_ok: instr = f"1. Open manually:\n '{fs_path}'\n" + instr
        self.show_crop_confirmation(instr)
    def _take_temp_screenshot(self, filename="_fs_temp.png"):
        try:
            fp = os.path.join(SCREENSHOTS_FOLDER, filename); os.makedirs(os.path.dirname(fp), exist_ok=True)
            pyautogui.screenshot().save(fp); self.log(f"Temp shot: '{fp}'"); return fp
        except Exception as e: self.log(f"Screenshot err: {e}"); messagebox.showerror("Error", f"Screenshot fail: {e}", parent=self.root); return None
    def _cleanup_temp_file(self, fp):
        if fp and os.path.exists(fp):
            try: os.remove(fp)
            except Exception as e: self.log(f"Warn: cleanup fail '{fp}': {e}")
    def show_crop_confirmation(self, instr):
        if hasattr(self, 'crop_win') and self.crop_win.winfo_exists(): self.crop_win.lift(); return
        self.crop_win = tk.Toplevel(self.root); self.crop_win.title("Confirm Crop"); self.crop_win.transient(self.root)
        self.crop_win.grab_set(); self.crop_win.resizable(False, False)
        self.temp_crop_info["t_fn_var"] = tk.StringVar(value=self.temp_crop_info['temp_save_filename'])
        n_fr = ttk.Frame(self.crop_win); n_fr.pack(pady=(10, 5), padx=10, fill=tk.X)
        ttk.Label(n_fr, text="Temp Name:").pack(side=tk.LEFT)
        n_ent = ttk.Entry(n_fr, textvariable=self.temp_crop_info["t_fn_var"], state='readonly', width=40); n_ent.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        cp_btn = ttk.Button(n_fr, text="Copy", command=self.copy_temp_crop_name); cp_btn.pack(side=tk.LEFT, padx=5); self.temp_crop_info["cp_btn"] = cp_btn
        msg = ttk.Label(self.crop_win, text=instr, justify=tk.LEFT, padding="10"); msg.pack(pady=(0, 10))
        btn_fr = ttk.Frame(self.crop_win); btn_fr.pack(pady=10)
        ok_btn = ttk.Button(btn_fr, text="Confirm Saved", command=self.confirm_crop_saved); ok_btn.pack(side=tk.LEFT, padx=10)
        can_btn = ttk.Button(btn_fr, text="Cancel Crop", command=self.cancel_crop); can_btn.pack(side=tk.LEFT, padx=10)
        self.root.wait_window(self.crop_win)
    def copy_temp_crop_name(self):
        if self.temp_crop_info and "t_fn_var" in self.temp_crop_info:
            t_nm = self.temp_crop_info["t_fn_var"].get()
            try:
                self.root.clipboard_clear(); self.root.clipboard_append(t_nm); self.log(f"Copied: {t_nm}")
                if "cp_btn" in self.temp_crop_info:
                     btn = self.temp_crop_info["cp_btn"]; orig_txt = btn.cget("text")
                     btn.config(text="Copied!", state=tk.DISABLED); self.root.after(1500, lambda: btn.config(text=orig_txt, state=tk.NORMAL))
            except tk.TclError: self.log("Clipboard err."); messagebox.showwarning("Error", "Clipboard access failed.", parent=self.crop_win)
        else: self.log("Err copying: No info.")
    def confirm_crop_saved(self):
        info = self.temp_crop_info; fs_path = info.get('fullscreen_path'); t_path = info.get('temp_save_path'); final_path = info.get('final_output_path'); fn = info.get('desired_filename')
        if not info or not t_path or not final_path or not fn:
            self.log("Crop confirm err: Missing info."); messagebox.showerror("Internal Error", "Missing crop info.", parent=self.crop_win)
            self._cleanup_temp_file(fs_path); self.close_crop_confirmation(); return
        if os.path.exists(t_path):
            self.log(f"Found temp: '{info['temp_save_filename']}'")
            try:
                if os.path.exists(final_path) and not messagebox.askyesno("Overwrite?", f"'{fn}' exists. Overwrite?", parent=self.crop_win):
                    self.log("Rename cancelled."); messagebox.showinfo("Cancelled", f"Kept temp: {t_path}", parent=self.crop_win); self._cleanup_temp_file(fs_path); self.close_crop_confirmation(); return
                elif os.path.exists(final_path): os.remove(final_path); self.log(f"Removed existing: '{fn}'")
                shutil.move(t_path, final_path); self.log(f"Renamed to '{fn}'."); messagebox.showinfo("Success", f"Saved: {final_path}", parent=self.crop_win); self._cleanup_temp_file(fs_path)
            except Exception as e: self.log(f"Rename err: {e}"); messagebox.showerror("Error", f"Rename fail: {e}\n\nKept temp: {t_path}", parent=self.crop_win); self._cleanup_temp_file(fs_path)
        else: self.log(f"Err: Temp not found: '{info['temp_save_filename']}'"); messagebox.showerror("Not Found", f"Temp file not found:\n{t_path}", parent=self.crop_win); self._cleanup_temp_file(fs_path)
        self.close_crop_confirmation()
    def cancel_crop(self):
        self.log("Crop cancelled.");
        if self.temp_crop_info: self._cleanup_temp_file(self.temp_crop_info.get('fullscreen_path')); self._cleanup_temp_file(self.temp_crop_info.get('temp_save_path'))
        self.close_crop_confirmation()
    def close_crop_confirmation(self):
       if self.temp_crop_info and "t_fn_var" in self.temp_crop_info: del self.temp_crop_info["t_fn_var"]
       if self.temp_crop_info and "cp_btn" in self.temp_crop_info: del self.temp_crop_info["cp_btn"]
       self.temp_crop_info = {}
       if hasattr(self, 'crop_win') and self.crop_win.winfo_exists(): self.crop_win.destroy()

    # --- Macro Execution (Timeout/Interval logic updated) ---
    def run_selected_macro(self, debug=False):
        if not self.current_macro_name: messagebox.showwarning("No Macro", "Select macro.", parent=self.root); return
        if self.macro_running: messagebox.showwarning("Running", "Macro running.", parent=self.root); return
        actions = self._load_macro_actions(self.current_macro_name)
        if actions is None: messagebox.showerror("Load Error", f"Load fail '{self.current_macro_name}'.", parent=self.root); return
        if not actions: messagebox.showinfo("Empty", f"'{self.current_macro_name}' empty.", parent=self.root); return
        self.macro_running = True; self.stop_macro_flag = False; self.disable_ui_for_run()
        self.btn_stop_macro.pack(side=tk.BOTTOM, pady=5); self.btn_stop_macro.config(state=tk.NORMAL, text="STOP MACRO")
        mode = "(DEBUG)" if debug else ""; self.log(f"--- Running: {self.current_macro_name} {mode} ---"); self.root.update_idletasks()
        self.macro_thread = threading.Thread(target=self._run_macro_thread, args=(actions, debug, self.current_macro_name), daemon=True); self.macro_thread.start(); self.check_macro_thread()
    def check_macro_thread(self):
        if self.macro_thread.is_alive(): self.root.after(200, self.check_macro_thread)
        else: self.on_macro_finished()
    def on_macro_finished(self):
        if self.macro_running: self.log(f"--- Macro finished ---"); self.macro_running = False; self.stop_macro_flag = False; self.btn_stop_macro.pack_forget(); self.enable_ui_after_run()
    # --- Updated _run_macro_thread ---
    def _run_macro_thread(self, actions, debug, name):
        total_steps = len(actions)
        for i, step in enumerate(actions):
            if self.stop_macro_flag: self.log("Stopped by user."); break
            action_type = step.get('action', 'Unknown'); self.log(f"\nStep {i+1}/{total_steps}: {action_type}"); self.root.update_idletasks()
            try:
                if action_type == "find_and_click":
                    template = step['template']; conf = float(step.get('confidence', DEFAULT_CONFIDENCE))
                    off_x = int(step.get('offset_x', 0)); off_y = int(step.get('offset_y', 0))
                    del_b = float(step.get('delay_before', DEFAULT_DELAY_BEFORE)); del_a = float(step.get('delay_after', DEFAULT_DELAY_AFTER))
                    dur = float(step.get('duration', DEFAULT_CLICK_DURATION)); btn = step.get('button', 'left')
                    rep_c = int(step.get('repeat_count', DEFAULT_REPEAT_COUNT)); rep_d = float(step.get('repeat_delay', DEFAULT_REPEAT_DELAY))
                    s_to = float(step.get('search_timeout', DEFAULT_SEARCH_TIMEOUT)); s_int = float(step.get('search_interval', DEFAULT_SEARCH_INTERVAL))
                    timeout_str = 'inf' if s_to == -1 else f'{s_to}s'
                    self.log(f"Searching '{template}' (Conf:{conf}, Timeout:{timeout_str}, Int:{s_int}s)"); self.root.update_idletasks()
                    start_time = time.time(); found_box = None
                    while True:
                        if self.stop_macro_flag: break
                        found_box = _locate_image_once(template, conf)
                        if found_box: self.log(f"Found at {found_box}."); break
                        elapsed = time.time() - start_time
                        if s_to != -1 and elapsed >= s_to: self.log(f"Timeout ({s_to}s). Not found."); break
                        sleep_start = time.time()
                        while time.time() - sleep_start < s_int:
                             if self.stop_macro_flag: break; time.sleep(0.05)
                        if self.stop_macro_flag: break
                    if self.stop_macro_flag: break
                    if found_box:
                        cx = found_box.left + found_box.width / 2 + off_x; cy = found_box.top + found_box.height / 2 + off_y
                        self.log(f"Target: ({cx:.1f}, {cy:.1f})"); self.root.update_idletasks(); proceed = True
                        if debug: proceed = debug_visualize(found_box, cx, cy)
                        if proceed and not perform_click(cx, cy, del_b, del_a, dur, btn, rep_c, rep_d): self.log(f"Step {i+1} FAIL: Click err/stop."); break
                        elif not proceed: self.log(f"Step {i+1} SKIP (Debug).")
                    else: self.log(f"Step {i+1} FAIL: Image '{template}' not found."); self.log("Continuing...") # Optionally break
                elif action_type == "click_at":
                    x = int(step['x']); y = int(step['y']); del_b = float(step.get('delay_before', DEFAULT_DELAY_BEFORE)); del_a = float(step.get('delay_after', DEFAULT_DELAY_AFTER))
                    dur = float(step.get('duration', DEFAULT_CLICK_DURATION)); btn = step.get('button', 'left'); rep_c = int(step.get('repeat_count', DEFAULT_REPEAT_COUNT)); rep_d = float(step.get('repeat_delay', DEFAULT_REPEAT_DELAY))
                    proceed = True;
                    if debug: proceed = debug_visualize(None, x, y)
                    if proceed and not perform_click(x, y, del_b, del_a, dur, btn, rep_c, rep_d): self.log(f"Step {i+1} FAIL: Click err/stop."); break
                    elif not proceed: self.log(f"Step {i+1} SKIP (Debug).")
                elif action_type == "delay":
                    dur = float(step.get('duration', 0)); self.log(f"Wait {dur}s..."); self.root.update_idletasks(); start_time = time.time()
                    while time.time() - start_time < dur:
                        if self.stop_macro_flag: break; time.sleep(0.1)
                    if self.stop_macro_flag: break
                elif action_type == "scroll":
                    direction = step.get('direction', DEFAULT_SCROLL_DIRECTION); amount = int(step.get('amount', DEFAULT_SCROLL_AMOUNT))
                    del_b = float(step.get('delay_before', DEFAULT_DELAY_BEFORE)); del_a = float(step.get('delay_after', DEFAULT_DELAY_AFTER))
                    if not perform_scroll(direction, amount, del_b, del_a): self.log(f"Step {i+1} FAIL: Scroll err/stop."); break
                elif action_type == "type_text":
                    text = step.get('text', ""); interval = float(step.get('interval', DEFAULT_TYPE_INTERVAL))
                    del_b = float(step.get('delay_before', DEFAULT_DELAY_BEFORE)); del_a = float(step.get('delay_after', DEFAULT_DELAY_AFTER))
                    if not perform_type(text, interval, del_b, del_a): self.log(f"Step {i+1} FAIL: Typing err/stop."); break
                else: self.log(f"Warn: Unknown action '{action_type}'.")
            except KeyError as e: self.log(f"Step {i+1} FAIL: Missing '{e}'."); break
            except Exception as e: self.log(f"Step {i+1} FAIL: Error: {e}\n{traceback.format_exc()}"); break
    def stop_macro_signal(self):
        if self.macro_running and not self.stop_macro_flag: self.log(">>> STOP signal <<<"); self.stop_macro_flag = True; self.btn_stop_macro.config(state=tk.DISABLED, text="Stopping...")
    def disable_ui_for_run(self):
         for btn in [self.btn_new, self.btn_edit, self.btn_run, self.btn_run_debug, self.btn_delete_macro, self.btn_crop_utility]: btn.config(state=tk.DISABLED)
         self.macro_listbox.config(state=tk.DISABLED)
         if self.editor_frame.winfo_ismapped():
             for child in self.step_controls_frame.winfo_children(): child.config(state=tk.DISABLED); self.steps_listbox.config(state=tk.DISABLED)
    def enable_ui_after_run(self):
         self.macro_listbox.config(state=tk.NORMAL); self.update_macro_buttons() # Handles enabling based on selection
         # Crop should be generally enabled if not running
         self.btn_crop_utility.config(state=tk.NORMAL if not self.macro_running else tk.DISABLED)
         if self.editor_frame.winfo_ismapped(): # If editor was open
              self.steps_listbox.config(state=tk.NORMAL); self.update_step_buttons()
              self.btn_add_step.config(state=tk.NORMAL); self.btn_save_macro.config(state=tk.NORMAL); self.btn_cancel_edit.config(state=tk.NORMAL)
    def on_closing(self):
        if self.macro_running and messagebox.askyesno("Exit?", "Macro running. Stop & exit?", parent=self.root): self.stop_macro_signal(); self.root.after(500, self.root.destroy)
        elif self.editor_frame.winfo_ismapped() and messagebox.askyesno("Exit?", "Editor open. Discard & exit?", parent=self.root): self.root.destroy()
        elif not self.macro_running and not self.editor_frame.winfo_ismapped(): self.root.destroy()

# --- Dialog Classes (Updated layout logic) ---

class BaseStepDialog(simpledialog.Dialog):
    def __init__(self, parent, title=None, action_data=None):
        self.action_data = action_data or {}; default_action = self.action_data.get("action", "find_and_click")
        self.action_type_var = tk.StringVar(value=default_action); self.widgets = {}; self.current_frame = None
        super().__init__(parent, title)

    def body(self, master):
        type_frame = ttk.Frame(master); type_frame.pack(pady=5, fill=tk.X)
        ttk.Label(type_frame, text="Action Type:").pack(side=tk.LEFT, padx=5)
        radio_frame = ttk.Frame(type_frame); radio_frame.pack(side=tk.LEFT)
        radio_state = tk.DISABLED if self.action_data else tk.NORMAL
        action_types = [("Find & Click", "find_and_click"), ("Click At", "click_at"), ("Delay", "delay"), ("Scroll", "scroll"), ("Type Text", "type_text")]
        for text, value in action_types: ttk.Radiobutton(radio_frame, text=text, variable=self.action_type_var, value=value, command=self.update_fields, state=radio_state).pack(anchor='w')
        self.fields_frame = ttk.LabelFrame(master, text="Action Settings", padding="10"); self.fields_frame.pack(pady=10, fill=tk.BOTH, expand=True)
        self.update_fields(); first_key = next(iter(self.widgets), None); return self.widgets.get(first_key)

    # --- Updated update_fields ---
    def update_fields(self):
        if self.current_frame: self.current_frame.destroy()
        self.widgets = {}; action = self.action_type_var.get()
        self.current_frame = ttk.Frame(self.fields_frame, padding=5); self.current_frame.pack(fill=tk.BOTH, expand=True)
        self.current_frame.columnconfigure(1, weight=1); row = 0
        if action == "find_and_click":
            ttk.Label(self.current_frame, text="--- Image Settings ---").grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 5)); row+=1
            self.add_field("Template File:", "template", row); row+=1
            self.add_field("Confidence:", "confidence", row, default=DEFAULT_CONFIDENCE); row+=1
            self.add_field("Search Timeout (s):", "search_timeout", row, default=DEFAULT_SEARCH_TIMEOUT); row+=1
            self.add_field("Search Interval (s):", "search_interval", row, default=DEFAULT_SEARCH_INTERVAL); row+=1
            ttk.Separator(self.current_frame, orient=tk.HORIZONTAL).grid(row=row, column=0, columnspan=2, sticky="ew", pady=5); row+=1
            ttk.Label(self.current_frame, text="--- Click Settings ---").grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 5)); row+=1
            # --- Offset moved here ---
            self.add_field("Offset X:", "offset_x", row, default=0, indent=True); row+=1
            self.add_field("Offset Y:", "offset_y", row, default=0, indent=True); row+=1
            self.add_click_fields(row, indent=True) # Add remaining click fields
        elif action == "click_at":
            ttk.Label(self.current_frame, text="--- Location ---").grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 5)); row+=1
            self.add_field("X Coordinate:", "x", row); row+=1
            self.add_field("Y Coordinate:", "y", row); row+=1
            ttk.Separator(self.current_frame, orient=tk.HORIZONTAL).grid(row=row, column=0, columnspan=2, sticky="ew", pady=5); row+=1
            ttk.Label(self.current_frame, text="--- Click Settings ---").grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 5)); row+=1
            self.add_click_fields(row, indent=True)
        elif action == "delay": self.add_field("Duration (s):", "duration", row, default=1.0); row+=1
        elif action == "scroll":
            self.add_field("Direction (up/down):", "direction", row, default=DEFAULT_SCROLL_DIRECTION); row+=1
            self.add_field("Amount (lines):", "amount", row, default=DEFAULT_SCROLL_AMOUNT); row+=1
            self.add_common_delay_fields(row)
        elif action == "type_text":
            self.add_field("Text to Type:", "text", row, is_text=True); row+=1
            self.add_field("Interval (s):", "interval", row, default=DEFAULT_TYPE_INTERVAL); row+=1
            self.add_common_delay_fields(row)

    # --- add_field (Unchanged) ---
    def add_field(self, label_text, key, row, default="", indent=False, is_text=False):
        value = self.action_data.get(key, default); label_padx = (25, 5) if indent else (5, 5); entry_padx = (5, 5)
        lbl = ttk.Label(self.current_frame, text=label_text); lbl.grid(row=row, column=0, sticky="w", padx=label_padx, pady=2)
        entry_width = 40 if is_text else 15
        entry = ttk.Entry(self.current_frame, width=entry_width); entry.grid(row=row, column=1, sticky="ew", padx=entry_padx, pady=2)
        entry.insert(0, str(value)); self.widgets[key] = entry

    # --- Updated add_click_fields (Offset removed) ---
    def add_click_fields(self, start_row, indent=False):
        row = start_row
        self.add_field("Button:", "button", row, default='left', indent=indent); row+=1
        self.add_field("Repeat Count:", "repeat_count", row, default=DEFAULT_REPEAT_COUNT, indent=indent); row+=1
        self.add_field("Repeat Delay (s):", "repeat_delay", row, default=DEFAULT_REPEAT_DELAY, indent=indent); row+=1
        self.add_field("Click Duration (s):", "duration", row, default=DEFAULT_CLICK_DURATION, indent=indent); row+=1
        # Delays added via add_common_delay_fields now for click actions too
        self.add_common_delay_fields(row, indent=indent)


    # --- add_common_delay_fields (Unchanged) ---
    def add_common_delay_fields(self, start_row, indent=False):
        row = start_row
        self.add_field("Delay Before (s):", "delay_before", row, default=DEFAULT_DELAY_BEFORE, indent=indent); row+=1
        self.add_field("Delay After (s):", "delay_after", row, default=DEFAULT_DELAY_AFTER, indent=indent); row+=1

    # --- validate (Unchanged) ---
    def validate(self):
        self.result = {"action": self.action_type_var.get()}; action = self.result["action"]
        try:
            for key, widget in self.widgets.items():
                value_str = widget.get()
                if key in ['confidence','delay_before','delay_after','repeat_delay','interval'] or (key == 'duration' and action != 'delay'): value = float(value_str); self.result[key] = value
                elif key == 'search_timeout': value = float(value_str); self.result[key] = value
                elif key == 'search_interval': value = float(value_str); self.result[key] = value
                elif key == 'duration' and action == 'delay': value = float(value_str); self.result[key] = value
                elif key in ['offset_x','offset_y','x','y','amount']: self.result[key] = int(value_str)
                elif key == 'repeat_count': value = int(value_str); self.result[key] = value
                elif key == 'template': value = value_str.strip(); self.result[key] = value
                elif key == 'button': value = value_str.strip().lower(); self.result[key] = value
                elif key == 'direction': value = value_str.strip().lower(); self.result[key] = value
                elif key == 'text': self.result[key] = value_str
                else: self.result[key] = value_str

                # Add specific range validation after conversion
                if key in ['confidence','delay_before','delay_after','repeat_delay','interval','duration','search_interval'] and self.result[key] < 0: raise ValueError(f"'{key}' cannot be negative")
                if key == 'search_timeout' and self.result[key] < 0 and self.result[key] != -1: raise ValueError("Timeout must be positive or -1")
                if key == 'repeat_count' and self.result[key] < 1: raise ValueError("Repeat count >= 1")
                if key == 'amount' and action == 'scroll' and self.result[key] <= 0: raise ValueError("Scroll amount must be positive")
                if key == 'template' and not self.result[key]: raise ValueError("Template filename required")
                if key == 'button' and self.result[key] not in ['left','right','middle']: raise ValueError("Button: left, right, middle")
                if key == 'direction' and self.result[key] not in ['up','down']: raise ValueError("Direction: up or down")

            required = {"find_and_click":["template"],"click_at":["x","y"],"delay":["duration"],"scroll":["direction","amount"],"type_text":[]}
            missing = [rf for rf in required.get(action, []) if rf not in self.result]
            if missing: raise ValueError(f"Missing field(s): {', '.join(missing)}")
            return 1
        except ValueError as e: messagebox.showwarning("Invalid", f"{e}", parent=self); return 0
    def apply(self): pass

# --- Dialog Subclasses (Unchanged) ---
class AddStepDialog(BaseStepDialog):
     def __init__(self, parent, title="Add New Step"): super().__init__(parent, title=title, action_data=None)
class EditStepDialog(BaseStepDialog):
     def __init__(self, parent, action_data, title="Edit Step Details"): super().__init__(parent, title=title, action_data=action_data)

# --- Main Execution (Unchanged) ---
if __name__ == "__main__":
    if platform.system() == "Windows":
        try: from ctypes import windll; windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
             try: windll.user32.SetProcessDPIAware()
             except Exception: print("Warn: DPI awareness failed.")
    root = tk.Tk()
    app = MacroApp(root)
    root.mainloop()
