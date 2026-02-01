import random
from collections import deque
from typing import Tuple, Optional, List

from game_constants import Team, TileType, FoodType, ShopCosts
from robot_controller import RobotController
from item import Pan, Plate, Food

class BotPlayer:
    def __init__(self, map_copy):
        self.map = map_copy
        # We will dynamically find these locations
        self.assembly_counter = None
        self.cooker_loc = None
        
        # Bot States (Integers representing the current step in the workflow)
        self.bot_0_state = 0
        self.bot_1_state = 0

    def get_bfs_path(self, controller: RobotController, start: Tuple[int, int], target_predicate, obstacles: set = None) -> Optional[Tuple[int, int]]:
        '''
        Standard BFS to find path to a target.
        Handles dynamic obstacles (other bots) if provided.
        '''
        if obstacles is None: obstacles = set()
        queue = deque([(start, [])]) 
        visited = set([start])
        w, h = self.map.width, self.map.height

        while queue:
            (curr_x, curr_y), path = queue.popleft()
            tile = controller.get_tile(controller.get_team(), curr_x, curr_y)
            if target_predicate(curr_x, curr_y, tile):
                if not path: return (0, 0) 
                return path[0] 

            for dx in [0, -1, 1]:
                for dy in [0, -1, 1]:
                    if dx == 0 and dy == 0: continue
                    nx, ny = curr_x + dx, curr_y + dy
                    if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited:
                        # Check static walkability AND dynamic obstacles
                        if controller.get_map().is_tile_walkable(nx, ny) and (nx, ny) not in obstacles:
                            visited.add((nx, ny))
                            queue.append(((nx, ny), path + [(dx, dy)]))
        return None

    def move_towards(self, controller: RobotController, bot_id: int, target_x: int, target_y: int) -> bool:
        '''
        Moves the bot towards the specific target coordinates.
        Returns True if adjacent to target (ready to interact).
        Returns False if moving or stuck.
        '''
        bot_state = controller.get_bot_state(bot_id)
        bx, by = bot_state['x'], bot_state['y']
        
        # Collect dynamic obstacles (other bots) to avoid collisions
        obstacles = set()
        for other_id in controller.get_team_bot_ids():
            if other_id != bot_id:
                other_info = controller.get_bot_state(other_id)
                obstacles.add((other_info['x'], other_info['y']))
                
        def is_adjacent_to_target(x, y, tile):
            return max(abs(x - target_x), abs(y - target_y)) <= 1
            
        if is_adjacent_to_target(bx, by, None): return True
        
        step = self.get_bfs_path(controller, (bx, by), is_adjacent_to_target, obstacles)
        
        # Fallback: If blocked, try finding path without obstacles (maybe they will move?)
        if step is None and obstacles:
             step = self.get_bfs_path(controller, (bx, by), is_adjacent_to_target, set())

        if step and (step[0] != 0 or step[1] != 0):
            controller.move(bot_id, step[0], step[1])
            return False 
        return False 

    def find_nearest_tile(self, controller: RobotController, bot_x: int, bot_y: int, tile_name: str) -> Optional[Tuple[int, int]]:
        '''
        Scans the map for the nearest tile of a specific type (e.g., "COUNTER", "COOKER", "SHOP").
        '''
        best_dist = 9999
        best_pos = None
        m = controller.get_map()
        for x in range(m.width):
            for y in range(m.height):
                tile = m.tiles[x][y]
                if tile.tile_name == tile_name:
                    dist = max(abs(bot_x - x), abs(bot_y - y))
                    if dist < best_dist:
                        best_dist = dist
                        best_pos = (x, y)
        return best_pos

    # --- HELPER FUNCTIONS ---
    def process_buy_item(self, controller: RobotController, bot_id: int, item_type) -> bool:
        '''
        Handles buying items. 
        Returns True if the bot has the item (bought or already holding).
        Returns False if still in progress (moving to shop).
        '''
        bot_info = controller.get_bot_state(bot_id)
        bx, by = bot_info['x'], bot_info['y']
        
        # Check if already holding the item
        holding = bot_info.get('holding')
        
        is_holding = False
        if holding:
            if isinstance(item_type, ShopCosts):
                if item_type == ShopCosts.PAN and holding['type'] == 'Pan':
                    is_holding = True
                elif item_type == ShopCosts.PLATE and holding['type'] == 'Plate':
                    is_holding = True
            elif isinstance(item_type, FoodType):
                if holding['type'] == 'Food' and holding.get('food_name') == item_type.food_name:
                    is_holding = True

        if is_holding:
            return True

        # Need to buy it -> Find Shop
        shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
        if not shop_pos: return False
        sx, sy = shop_pos
        
        if self.move_towards(controller, bot_id, sx, sy):
            if controller.get_team_money() >= item_type.buy_cost:
                controller.buy(bot_id, item_type, sx, sy)
                return False # Wait for next turn to confirm purchase
        
        return False

    def process_chop_at_counter(self, controller: RobotController, bot_id: int, counter_pos: Tuple[int, int]) -> bool:
        '''
        Handles chopping ingredients at a specific counter.
        Returns True if the item is chopped and ready.
        Returns False if in progress (moving, placing, chopping).
        '''
        cx, cy = counter_pos
        
        if self.move_towards(controller, bot_id, cx, cy):
            tile = controller.get_tile(controller.get_team(), cx, cy)
            item_on_counter = tile.item if tile else None
            
            # If nothing on counter, place what we are holding
            if item_on_counter is None:
                controller.place(bot_id, cx, cy)
                return False
            
            # If item on counter is food, check if chopped
            if isinstance(item_on_counter, Food):
                if item_on_counter.chopped:
                    return True # Done!
                else:
                    controller.chop(bot_id, cx, cy)
                    return False
        
        return False

    # --- ORDER LOGIC ---
    def get_priority_order(self, controller: RobotController):
        '''
        Returns the highest priority active order.
        Strategy: Returns the first active order found.
        '''
        orders = controller.get_orders()
        for order in orders:
            if order['is_active']:
                return order
        return None

    def get_missing_ingredients(self, controller: RobotController, order) -> List[str]:
        '''
        Checks the assembly counter for the current plate and returns missing ingredients
        for the given order.
        '''
        if not self.assembly_counter: return order['required']
        cx, cy = self.assembly_counter
        
        tile = controller.get_tile(controller.get_team(), cx, cy)
        
        # What is already on the plate?
        on_plate = []
        if tile and isinstance(tile.item, Plate):
            on_plate = [f.food_name for f in tile.item.food]
        
        # Determine missing items
        required = order['required']
        req_copy = list(required)
        for item in on_plate:
            if item in req_copy:
                req_copy.remove(item)
        
        return req_copy

    # --- BOT LOGIC ---

    def run_prep_bot(self, controller: RobotController, bot_id: int):
        '''
        Bot 0 (Prep): Responsible for preparing non-cooked ingredients (NOODLES, SAUCE, ONIONS).
        It identifies missing ingredients and brings them to the assembly counter (chopping if needed).
        '''
        bot_info = controller.get_bot_state(bot_id)
        if not self.assembly_counter: return
        assembly_x, assembly_y = self.assembly_counter

        # 1. Determine Goal
        prioritized_order = self.get_priority_order(controller)
        if not prioritized_order: return

        missing = self.get_missing_ingredients(controller, prioritized_order)
        
        # Filter for Prep Tasks
        prep_tasks = [item for item in missing if item in ['NOODLES', 'SAUCE', 'ONIONS']]
        
        if not prep_tasks: return

        target_item_name = prep_tasks[0]
        
        # Find Enum for target
        target_enum = None
        for f in FoodType:
            if f.food_name == target_item_name:
                target_enum = f
                break
        
        if not target_enum: return

        # --- PREP STATE MACHINE ---
        # 0: Init
        # 1: Buy Ingredient
        # 2: Deliver to Assembly
        # 3: Chop Cycle
        # 4: Pickup Chopped

        # Reset Logic if empty handed (and expecting to hold something)
        if self.bot_0_state > 1 and not bot_info.get('holding'):
             self.bot_0_state = 1

        if self.bot_0_state == 0:
            self.bot_0_state = 1

        elif self.bot_0_state == 1:
            if self.process_buy_item(controller, bot_id, target_enum):
                # Item acquired
                if target_enum.can_chop:
                     self.bot_0_state = 3 # Go chop
                else:
                     self.bot_0_state = 2 # Go place

        elif self.bot_0_state == 2:
            # Place on Assembly Counter
            if self.move_towards(controller, bot_id, assembly_x, assembly_y):
                tile = controller.get_tile(controller.get_team(), assembly_x, assembly_y)
                
                # If there is a Plate, add to it
                if tile and isinstance(tile.item, Plate):
                    if controller.add_food_to_plate(bot_id, assembly_x, assembly_y):
                        self.bot_0_state = 1 # Loop for next item
                else:
                    # Wait for plate to arrive (Meat Bot handles plate)
                    pass

        elif self.bot_0_state == 3:
            # Chop Cycle
            if self.process_chop_at_counter(controller, bot_id, (assembly_x, assembly_y)):
                self.bot_0_state = 4 # Pickup Chopped

        elif self.bot_0_state == 4:
            if self.move_towards(controller, bot_id, assembly_x, assembly_y):
                if controller.pickup(bot_id, assembly_x, assembly_y):
                    self.bot_0_state = 2 # Now deliver the chopped item


    def run_cook_bot(self, controller: RobotController, bot_id: int):
        '''
        Bot 1 (Cook): Responsible for MEAT, EGG, PAN, and PLATES.
        It prioritizes cooking first (to free up the counter) then manages plating.
        '''
        bot_info = controller.get_bot_state(bot_id)
        if not self.assembly_counter or not self.cooker_loc: return
        assembly_x, assembly_y = self.assembly_counter
        cooker_x, cooker_y = self.cooker_loc

        prioritized_order = self.get_priority_order(controller)
        if not prioritized_order: return
        
        # Check if Plate is missing on Assembly Counter
        tile = controller.get_tile(controller.get_team(), assembly_x, assembly_y)
        plate_missing = True
        if tile and isinstance(tile.item, Plate):
            plate_missing = False
        
        missing = self.get_missing_ingredients(controller, prioritized_order)
        cook_tasks_raw = [item for item in missing if item in ['MEAT', 'EGG']]

        # Filter cook_tasks: Exclude if already on Pan or currently Held
        tile_pan = controller.get_tile(controller.get_team(), cooker_x, cooker_y)
        pan_item = None
        if tile_pan and isinstance(tile_pan.item, Pan) and tile_pan.item.food:
             pan_item = tile_pan.item.food.food_name
        
        held = bot_info.get('holding')
        held_name = None
        if held:
             # Identify what is held safely
             if held.get('type') == 'Food':
                 held_name = held.get('food_name')
             elif held.get('type') in ['Pan', 'Plate']:
                 held_name = held.get('type')
        
        cook_tasks = []
        for t in cook_tasks_raw:
             if t == pan_item: continue
             if t == held_name: continue
             cook_tasks.append(t)

        # --- COOK BOT STATE MACHINE ---
        # 0: Init / Check Pan
        # 1: Buy Pan
        # 2: Decision Hub (Cook vs Plate vs Submit)
        
        # Plate Sub-states:
        # 8: Buy Plate
        # 9: Place Plate
        
        # Ingredient/Cooking Sub-states:
        # 20: Buy Ingredient
        # 21: Chop (Not used for Meat/Egg usually, but supported)
        # 22: Pickup
        # 23: Place on Pan
        # 24: Wait for Cook
        # 25: Pickup Cooked
        # 26: Deliver to Plate
        
        # Submit Logic:
        # 50: Pickup Plate
        # 51: Submit

        # --- LOGIC ---
        
        if self.bot_1_state == 0:
            # Ensure Pan exists on Cooker
            tile = controller.get_tile(controller.get_team(), cooker_x, cooker_y)
            if tile and isinstance(tile.item, Pan):
                self.bot_1_state = 2
            else:
                self.bot_1_state = 1

        elif self.bot_1_state == 1:
            if self.process_buy_item(controller, bot_id, ShopCosts.PAN):
                if self.move_towards(controller, bot_id, cooker_x, cooker_y):
                    if controller.place(bot_id, cooker_x, cooker_y):
                        self.bot_1_state = 2

        elif self.bot_1_state == 2:
            # DECISION: Prioritize COOKING to avoid blocking Assembly Counter with a Plate too early.
            
            if cook_tasks:
                if not held:
                    self.bot_1_state = 20
            elif plate_missing:
                # Use idle time (or if no cook tasks) to get Plate
                self.bot_1_state = 8
            else:
                # No cook tasks left (or item is currently cooking) AND Plate is present.
                
                # Check Pan Status: Is food ready or burning?
                if pan_item:
                     self.bot_1_state = 24 # Go wait/pickup
                elif not missing:
                    self.bot_1_state = 50 # Ready to submit!
                else:
                    # Waiting for Prep bot to finish their part
                    pass

        # --- Plate Logic ---
        elif self.bot_1_state == 8:
            if self.process_buy_item(controller, bot_id, ShopCosts.PLATE):
                self.bot_1_state = 9
        elif self.bot_1_state == 9:
            if self.move_towards(controller, bot_id, assembly_x, assembly_y):
                tile = controller.get_tile(controller.get_team(), assembly_x, assembly_y)
                if tile and tile.item is None:
                    if controller.place(bot_id, assembly_x, assembly_y):
                        self.bot_1_state = 2
                elif tile and isinstance(tile.item, Plate):
                    self.bot_1_state = 2 # Already there

        # --- Ingredient Logic ---
        elif self.bot_1_state == 20:
            
            if not cook_tasks: 
                self.bot_1_state = 2
                return
            
            target_name = cook_tasks[0]
            target_enum = next((f for f in FoodType if f.food_name == target_name), None)
            
            if self.process_buy_item(controller, bot_id, target_enum):
                if target_enum.can_chop:
                    self.bot_1_state = 21
                else:
                    self.bot_1_state = 23 # Direct to pan

        elif self.bot_1_state == 21:
            # Chop (Rare for cook items in this config)
            if self.process_chop_at_counter(controller, bot_id, (assembly_x, assembly_y)):
                self.bot_1_state = 22
        
        elif self.bot_1_state == 22:
            if self.move_towards(controller, bot_id, assembly_x, assembly_y):
                if controller.pickup(bot_id, assembly_x, assembly_y):
                    self.bot_1_state = 23
        
        elif self.bot_1_state == 23:
            # Place on Pan
            if self.move_towards(controller, bot_id, cooker_x, cooker_y):
                 if controller.place(bot_id, cooker_x, cooker_y):
                     self.bot_1_state = 24

        elif self.bot_1_state == 24:
            # Wait for Cook
            
            # Optimization: If Plate is missing while we wait, go get it!
            if plate_missing:
                self.bot_1_state = 8
                return

            # Check pan status
            tile = controller.get_tile(controller.get_team(), cooker_x, cooker_y)
            if tile and isinstance(tile.item, Pan) and tile.item.food:
                food = tile.item.food
                if food.cooked_stage == 1: # Cooked (Perfect)
                    if controller.take_from_pan(bot_id, cooker_x, cooker_y):
                        self.bot_1_state = 26
                elif food.cooked_stage == 2: # Burnt
                     controller.take_from_pan(bot_id, cooker_x, cooker_y)
                     self.bot_1_state = 16 # Trash it
            else:
                 # Pan empty? Maybe we missed it or haven't placed yet.
                 pass

        elif self.bot_1_state == 26:
            # Deliver to Plate at Assembly
            if self.move_towards(controller, bot_id, assembly_x, assembly_y):
                if controller.add_food_to_plate(bot_id, assembly_x, assembly_y):
                    self.bot_1_state = 2 # Loop

        # --- Submit Logic ---
        elif self.bot_1_state == 50:
            if self.move_towards(controller, bot_id, assembly_x, assembly_y):
                    if controller.pickup(bot_id, assembly_x, assembly_y):
                        self.bot_1_state = 51

        elif self.bot_1_state == 51:
            submit_pos = self.find_nearest_tile(controller, bot_info['x'], bot_info['y'], "SUBMIT")
            ux, uy = submit_pos
            if self.move_towards(controller, bot_id, ux, uy):
                if controller.submit(bot_id, ux, uy):
                    self.bot_1_state = 2

        # --- Trash Logic ---
        elif self.bot_1_state == 16:
            trash_pos = self.find_nearest_tile(controller, bot_info['x'], bot_info['y'], "TRASH")
            if not trash_pos: return
            tx, ty = trash_pos
            if self.move_towards(controller, bot_id, tx, ty):
                if controller.trash(bot_id, tx, ty):
                    self.bot_1_state = 2 # Restart

    def play_turn(self, controller: RobotController):
        # Logging (Optional: Helpful for debugging)
        # try:
        #      with open("red_log.txt", "a") as f:
        #          f.write(f"Turn: B0={self.bot_0_state} B1={self.bot_1_state}\n")
        #          p_order = self.get_priority_order(controller)
        #          if p_order:
        #              miss = self.get_missing_ingredients(controller, p_order)
        #              f.write(f"  Order={p_order['order_id']} Req={p_order['required']} Miss={miss}\n")
        #          else:
        #              f.write("  No active order\n")
        # except: pass

        my_bots = controller.get_team_bot_ids()
        if not my_bots: return
    
        # Determine locations once
        bot_0_info = controller.get_bot_state(my_bots[0])
        
        if self.assembly_counter is None:
            self.assembly_counter = self.find_nearest_tile(controller, bot_0_info['x'], bot_0_info['y'], "COUNTER")
        if self.cooker_loc is None:
            self.cooker_loc = self.find_nearest_tile(controller, bot_0_info['x'], bot_0_info['y'], "COOKER")

        # Run strategies for first two bots
        if len(my_bots) >= 1:
            self.run_prep_bot(controller, my_bots[0])
        
        if len(my_bots) >= 2:
            self.run_cook_bot(controller, my_bots[1])
        