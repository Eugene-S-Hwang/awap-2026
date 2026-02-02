import random
from collections import deque
from typing import Tuple, Optional, List

from game_constants import Team, TileType, FoodType, ShopCosts
from robot_controller import RobotController
from item import Pan, Plate, Food
from enum import Enum
import math

class States(Enum):
    NOTHING = -1
    INIT = 0
    BUY_PAN = 1
    BUY_FOOD = 2
    PLACE_ON_COUNTER = 3
    CHOP_FOOD = 4
    PICKUP_CHOPPED = 5
    COOK_FOOD = 6
    BUY_PLATE = 7
    PLACE_PLATE = 8
    ADD_FOOD = 9
    WAIT_AND_TAKE = 10
    SUBMIT = 11
    WASH_DISH = 12
    GET_PLATE_FROM_SINKTABLE = 13
    TRASH = 14

class BotPlayer:
    def __init__(self, map_copy):
        self.map = map_copy
        self.assembly_counter = None 
        self.cooker_loc = None
        self.submit_pos = None
        self.sink_pos = None
        self.sinktable_pos = None
        self.my_bot_id = None
        self.current_order = None
        self.orders = None
        self.tile_cache = {}
        self._build_tile_cache()

        self.path_cache = {}  # Cache computed paths
        self.cache_hits = 0
        self.cache_misses = 0

        self.state = States.INIT

    # def get_bfs_path(self, controller: RobotController, start: Tuple[int, int], target_predicate) -> Optional[Tuple[int, int]]:
    #     queue = deque([(start, [])]) 
    #     visited = set([start])
    #     w, h = self.map.width, self.map.height

    #     while queue:
    #         (curr_x, curr_y), path = queue.popleft()
    #         tile = controller.get_tile(controller.get_team(), curr_x, curr_y)
    #         if target_predicate(curr_x, curr_y, tile):
    #             if not path: return (0, 0) 
    #             return path[0] 

    #         for dx in [0, -1, 1]:
    #             for dy in [0, -1, 1]:
    #                 if dx == 0 and dy == 0: continue
    #                 nx, ny = curr_x + dx, curr_y + dy
    #                 if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited:
    #                     if controller.get_map(controller.get_team()).is_tile_walkable(nx, ny):
    #                         visited.add((nx, ny))
    #                         queue.append(((nx, ny), path + [(dx, dy)]))
    #     return None

    # def move_towards(self, controller: RobotController, bot_id: int, target_x: int, target_y: int) -> bool:
    #     bot_state = controller.get_bot_state(bot_id)
    #     bx, by = bot_state['x'], bot_state['y']
    #     def is_adjacent_to_target(x, y, tile):
    #         return max(abs(x - target_x), abs(y - target_y)) <= 1
    #     if is_adjacent_to_target(bx, by, None): return True
    #     step = self.get_bfs_path(controller, (bx, by), is_adjacent_to_target)
    #     if step and (step[0] != 0 or step[1] != 0):
    #         controller.move(bot_id, step[0], step[1])
    #         return False 
    #     return False 

    # def find_nearest_tile(self, controller: RobotController, bot_x: int, bot_y: int, tile_name: str) -> Optional[Tuple[int, int]]:
    #     best_dist = 9999
    #     best_pos = None
    #     m = controller.get_map(controller.get_team())
    #     for x in range(m.width):
    #         for y in range(m.height):
    #             tile = m.tiles[x][y]
    #             if tile.tile_name == tile_name:
    #                 dist = max(abs(bot_x - x), abs(bot_y - y))
    #                 if dist < best_dist:
    #                     best_dist = dist
    #                     best_pos = (x, y)
    #     return best_pos
        
    def get_bfs_path(self, controller: RobotController, start: Tuple[int, int], target: Tuple[int, int]) -> Optional[Tuple[int, int]]:
        """BFS with caching - now takes target coordinates instead of predicate"""
        cache_key = (start, target)
        
        # Check cache
        if cache_key in self.path_cache:
            self.cache_hits += 1
            return self.path_cache[cache_key]
        
        self.cache_misses += 1
        
        queue = deque([(start, [])])
        visited = set([start])
        w, h = self.map.width, self.map.height

        obstacles = set()

        for bots in controller.get_team_bot_ids(controller.get_team()):
            bot_info = controller.get_bot_state(bots)
            obstacles.add((bot_info['x'], bot_info['y']))
        
        while queue:
            (curr_x, curr_y), path = queue.popleft()
            
            # Check if adjacent to target (Chebyshev distance)
            if max(abs(curr_x - target[0]), abs(curr_y - target[1])) <= 1:
                result = path[0] if path else (0, 0)
                self.path_cache[cache_key] = result
                return result
            
            for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0), (-1, -1), (-1, 1), (1, -1), (1, 1)]:
                nx, ny = curr_x + dx, curr_y + dy
                if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited and (nx, ny) not in obstacles:
                    if self.map.tiles[nx][ny].is_walkable:  # Use cached map instead of controller call
                        visited.add((nx, ny))
                        queue.append(((nx, ny), path + [(dx, dy)]))
        
        self.path_cache[cache_key] = None
        return None

    def move_towards(self, controller: RobotController, bot_id: int, target_x: int, target_y: int) -> bool:
        bot_state = controller.get_bot_state(bot_id)
        bx, by = bot_state['x'], bot_state['y']
        
        # Check if already adjacent
        if max(abs(bx - target_x), abs(by - target_y)) <= 1:
            return True
        
        step = self.get_bfs_path(controller, (bx, by), (target_x, target_y))
        if step and step != (0, 0):
            controller.move(bot_id, step[0], step[1])
            return False
        return False

    def _build_tile_cache(self):
        """Build cache of all tile locations once at initialization"""
        for x in range(self.map.width):
            for y in range(self.map.height):
                tile = self.map.tiles[x][y]
                tile_name = tile.tile_name
                if tile_name not in self.tile_cache:
                    self.tile_cache[tile_name] = []
                self.tile_cache[tile_name].append((x, y))

    def find_nearest_tile(self, controller: RobotController, bot_x: int, bot_y: int, tile_name: str) -> Optional[Tuple[int, int]]:
        """Find nearest tile using cached locations"""
        if tile_name not in self.tile_cache:
            return None
        
        positions = self.tile_cache[tile_name]
        if not positions:
            return None
        
        # Find minimum using Chebyshev distance
        return min(positions, key=lambda pos: max(abs(bot_x - pos[0]), abs(bot_y - pos[1])))
    
    def estimate_travel_time(self, start: Tuple[int, int], end: Tuple[int, int]) -> int:
        """Estimate travel time using Chebyshev distance (max of dx, dy)"""
        return max(abs(start[0] - end[0]), abs(start[1] - end[1]))

    def calculate_order_time_fast(self, controller: RobotController, order: dict, bot_x: int, bot_y: int) -> int:
        """Fast estimate using direct distances instead of pathfinding"""
        
        # Find key locations (cached)
        shop = self.tile_cache.get("SHOP", [None])[0]
        counter = self.tile_cache.get("COUNTER", [None])[0]
        cooker = self.tile_cache.get("COOKER", [None])[0]
        submit = self.tile_cache.get("SUBMIT", [None])[0]
        
        if not all([shop, counter, cooker, submit]):
            # Fallback
            return len(order['required']) * 30
        
        est_time = 0
        current_pos = (bot_x, bot_y)
        
        # Average distance for a workflow
        avg_shop_to_counter = self.estimate_travel_time(shop, counter)
        avg_counter_to_cooker = self.estimate_travel_time(counter, cooker)
        avg_cooker_to_submit = self.estimate_travel_time(cooker, submit)
        
        for food_name in order['required']:
            food_type = FoodType[food_name]
            
            # Shop trip
            est_time += self.estimate_travel_time(current_pos, shop) + 1
            current_pos = shop
            
            # Chopping workflow
            if food_type.can_chop:
                est_time += avg_shop_to_counter + 1 + 2 + 1  # travel + place + chop + pickup
                current_pos = counter
            
            # Cooking workflow
            if food_type.can_cook:
                est_time += avg_counter_to_cooker + 1 + 20 + 1  # travel + place + cook + take
                current_pos = cooker
            
            # To submit
            est_time += self.estimate_travel_time(current_pos, submit) + 1
            current_pos = submit
        
        # Pan/plate setup overhead
        # est_time += 15
        
        return est_time
    
    def process_orders(self, controller: RobotController):
        self.orders = []
        orders = controller.get_orders(controller.get_team())
        # print("Raw Orders: ", orders)
        current_turn = controller.get_turn()

        bot_info = controller.get_bot_state(controller.get_team_bot_ids(controller.get_team())[0])
        bot_x, bot_y = bot_info['x'], bot_info['y']
        for order in orders:
            if order['expires_turn'] < current_turn: continue
            reward = order['reward']
            penalty = order['penalty']
            cost = 0
            est_time = 0
            for food in order['required']:
                cost += FoodType[food].buy_cost
                est_time += FoodType[food].can_cook * 20 + FoodType[food].can_chop * 2 + 20
                # est_time = self.calculate_order_time_fast(controller, order, bot_x, bot_y)
            
            time_remaining = order['expires_turn'] - current_turn
            time_buffer = time_remaining - est_time

            if controller.get_turn() + est_time < order["created_turn"]:
                continue
            
            # Convert time buffer to success probability using sigmoid
            p_success = 1.0 / (1.0 + math.exp(-time_buffer / 5.0))
            
            # Expected value
            ev = (reward - cost) * p_success - (penalty + cost) * (1 - p_success)
            order['ev'] = ev
            order['cost'] = cost
            order['est_time'] = est_time
            order['p_success'] = p_success
            self.orders.append(order)
        self.orders.sort(key=lambda x: x['ev'], reverse=True)
        # print(self.orders)
    
    # def update_orders(self, controller: RobotController):
    #     orders = controller.get_orders(controller.get_team())
    #     current_turn = controller.get_turn()
    #     for order in orders:
    #         if order['is_active'] == False: continue
    #         reward = order['reward']
    #         penalty = order['penalty']
    #         cost = order['cost']
    #         est_time = order['est_time']
    #         time_remaining = order['expires_turn'] - current_turn
    #         time_buffer = time_remaining - est_time
            
    #         # Convert time buffer to success probability using sigmoid
    #         p_success = 1.0 / (1.0 + math.exp(-time_buffer / 5.0))
            
    #         # Expected value
    #         ev = (reward - cost) * p_success - (penalty + cost) * (1 - p_success)
    #         order['ev'] = ev
    #         order['p_success'] = p_success
    #     self.orders.sort(key=lambda x: x['ev'], reverse=True)

    def play_turn(self, controller: RobotController):
        my_bots = controller.get_team_bot_ids(controller.get_team())
        if not my_bots: return
    
        self.my_bot_id = my_bots[0]
        bot_id = self.my_bot_id

        # self.orders = controller.get_orders(controller.get_team())
        if(not self.current_order):
            # if self.orders is None:
            self.process_orders(controller)
            # else:
            #     self.update_orders(controller)
            for order in self.orders:
                # print("Check: ", order["claimed_by"])
                # print(order)
                if order["claimed_by"] is None and order["reward"] > order["cost"] and order["p_success"] > 0.5:
                    if self.state == States.NOTHING:
                        self.state = States.INIT
                    self.current_order = order
                    # print(self.current_order)
                    # print(controller.get_turn())
                    break
        
        
        bot_info = controller.get_bot_state(bot_id)
        bx, by = bot_info['x'], bot_info['y']

        # if self.assembly_counter is None:
        #     self.assembly_counter = self.find_nearest_tile(controller, bx, by, "COUNTER")
        # if self.cooker_loc is None:
        #     self.cooker_loc = self.find_nearest_tile(controller, bx, by, "COOKER")
        if self.submit_pos is None:
            self.submit_pos = self.find_nearest_tile(controller, bx, by, "SUBMIT")
        # if self.sink_pos is None:
        #     self.sink_pos = self.find_nearest_tile(controller, bx, by, "SINK")
        # if self.sinktable_pos is None:
        #     self.sinktable_pos = self.find_nearest_tile(controller, bx, by, "SINKTABLE")
            
        self.assembly_counter = self.find_nearest_tile(controller, bx, by, "COUNTER")
        self.cooker_loc = self.find_nearest_tile(controller, bx, by, "COOKER")
        # self.submit_pos = self.find_nearest_tile(controller, bx, by, "SUBMIT")

        if not self.assembly_counter or not self.cooker_loc or not self.submit_pos: 
            return

        cx, cy = self.assembly_counter
        kx, ky = self.cooker_loc
        ux, uy = self.submit_pos
        # wx, wy = self.sink_pos
        # stx, sty = self.sinktable_pos

        if not self.get_bfs_path(controller, (bx, by), (cx, cy)) or not self.get_bfs_path(controller, (bx, by), (kx, ky)) or not self.get_bfs_path(controller, (bx, by), (ux, uy)): # or not self.get_bfs_path(controller, (bx, by), (wx, wy)) or not self.get_bfs_path(controller, (bx, by), (stx, sty)):
            return

        # if self.state in [2, 8, 10] and bot_info.get('holding'):
        #     self.state = 16

        #state 0: init + checking the pan

        # print(self.state)
        if self.state == States.INIT:
            if(not self.current_order):
                self.state = States.NOTHING
            else:
                kTile = controller.get_tile(controller.get_team(), kx, ky)
                uTile = controller.get_tile(controller.get_team(), ux, uy)
                if kTile and isinstance(kTile.item, Pan) and uTile and isinstance(uTile.item, Plate):
                    self.state = States.BUY_FOOD
                elif kTile and isinstance(kTile.item, Pan):
                    self.state = States.BUY_PLATE
                else:
                    self.state = States.BUY_PAN

        elif self.state == States.BUY_PAN:
            holding = bot_info.get('holding')
            if holding: # check if it is a pan if needed
                if self.move_towards(controller, bot_id, kx, ky):
                    if controller.place(bot_id, kx, ky):
                        self.state = States.INIT
            else:
                shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
                if not shop_pos: return
                sx, sy = shop_pos
                if self.move_towards(controller, bot_id, sx, sy):
                    if controller.get_team_money(controller.get_team()) >= ShopCosts.PAN.buy_cost:
                        controller.buy(bot_id, ShopCosts.PAN, sx, sy)

        elif self.state == States.BUY_FOOD:
            if len(self.current_order["required"]) == 0:
                self.state = States.SUBMIT
            elif bot_info["holding"]:
                self.state = States.TRASH
            else:
                shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
                sx, sy = shop_pos
                if self.move_towards(controller, bot_id, sx, sy):
                    buyFood = self.current_order["required"].pop()
                    if(buyFood == "MEAT"):
                        if controller.get_team_money(controller.get_team()) >= FoodType.MEAT.buy_cost:
                            if controller.buy(bot_id, FoodType.MEAT, sx, sy):
                                self.state = States.PLACE_ON_COUNTER
                    elif(buyFood == "EGG"):
                        if controller.get_team_money(controller.get_team()) >= FoodType.EGG.buy_cost:
                            if controller.buy(bot_id, FoodType.EGG, sx, sy):
                                self.state = States.COOK_FOOD
                    elif(buyFood == "ONIONS"):
                        if controller.get_team_money(controller.get_team()) >= FoodType.ONIONS.buy_cost:
                            if controller.buy(bot_id, FoodType.ONIONS, sx, sy):
                                self.state = States.PLACE_ON_COUNTER
                    elif(buyFood == "NOODLES"):
                        if controller.get_team_money(controller.get_team()) >= FoodType.NOODLES.buy_cost:
                            if controller.buy(bot_id, FoodType.NOODLES, sx, sy):
                                self.state = States.ADD_FOOD
                    elif(buyFood == "SAUCE"):
                        if controller.get_team_money(controller.get_team()) >= FoodType.SAUCE.buy_cost:
                            if controller.buy(bot_id, FoodType.SAUCE, sx, sy):
                                self.state = States.ADD_FOOD

        elif self.state == States.PLACE_ON_COUNTER:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.place(bot_id, cx, cy):
                    self.state = States.CHOP_FOOD

        elif self.state == States.CHOP_FOOD:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.chop(bot_id, cx, cy):
                    self.state = States.PICKUP_CHOPPED

        #state 5: pickup meat
        elif self.state == States.PICKUP_CHOPPED:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.pickup(bot_id, cx, cy):
                    food = controller.get_bot_state(bot_id)["holding"]
                    # print(food)
                    if(food["food_id"] in [0, 2]):
                        self.state = States.COOK_FOOD
                    else:
                        self.state = States.ADD_FOOD

        elif self.state == States.COOK_FOOD:
            if self.move_towards(controller, bot_id, kx, ky):
                # Using the NEW logic where place() starts cooking automatically
                if controller.place(bot_id, kx, ky):
                    self.state = States.WAIT_AND_TAKE

        #state 8: buy the plate
        elif self.state == States.BUY_PLATE:
            shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
            sx, sy = shop_pos
            if self.move_towards(controller, bot_id, sx, sy):
                if controller.get_team_money(controller.get_team()) >= ShopCosts.PLATE.buy_cost:
                    if controller.buy(bot_id, ShopCosts.PLATE, sx, sy):
                        self.state = States.PLACE_PLATE

        elif self.state == States.PLACE_PLATE:
            if not bot_info["holding"]:
                controller.pickup(bot_id, bx, by)
            else:
                if self.move_towards(controller, bot_id, ux, uy):
                    if controller.place(bot_id, ux, uy):
                        self.state = States.INIT

        elif self.state == States.ADD_FOOD:
            if self.move_towards(controller, bot_id, ux, uy):
                if controller.add_food_to_plate(bot_id, ux, uy):
                    if self.current_order["expires_turn"] <= controller.get_turn():
                        self.state = States.TRASH
                        self.current_order = None
                    else:
                        self.state = States.INIT

        elif self.state == States.WAIT_AND_TAKE:
            if self.move_towards(controller, bot_id, kx, ky):
                tile = controller.get_tile(controller.get_team(), kx, ky)
                if tile and isinstance(tile.item, Pan) and tile.item.food:
                    food = tile.item.food
                    if food.cooked_stage == 1:
                        if controller.take_from_pan(bot_id, kx, ky):
                            self.state = States.ADD_FOOD
                    elif food.cooked_stage == 2:
                        if controller.take_from_pan(bot_id, kx, ky):
                            self.state = States.TRASH

        elif self.state == States.SUBMIT:
            if self.move_towards(controller, bot_id, ux, uy):
                if not bot_info["holding"]:
                    controller.pickup(bot_id, ux, uy)
                else:
                    if self.current_order["created_turn"] <= controller.get_turn():
                        if controller.submit(bot_id, ux, uy):
                            self.current_order = None
                            # self.state = States.WASH_DISH
                            self.state = States.INIT
                        else:
                            if self.current_order["expires_turn"] <= controller.get_turn():
                                self.current_order = None
                            self.state = States.TRASH
        
        # elif self.state == States.WASH_DISH:
        #     if self.move_towards(controller, bot_id, wx, wy):
        #         st_tile = controller.get_tile(controller.get_team(), stx, sty)

        #         if st_tile and st_tile.num_clean_plates > 0:
        #             self.state = States.GET_PLATE_FROM_SINKTABLE
        #         else:
        #             if not controller.wash_sink(bot_id, wx, wy):
        #                 self.state = States.INIT
                    
        
        # elif self.state == States.GET_PLATE_FROM_SINKTABLE:
        #     if self.move_towards(controller, bot_id, stx, sty):
        #         if controller.take_clean_plate(bot_id, stx, sty):
        #             self.state = States.PLACE_PLATE

        elif self.state == States.TRASH:
            if not bot_info["holding"]:
                controller.pickup(bot_id, ux, uy)
            else:
                trash_pos = self.find_nearest_tile(controller, bx, by, "TRASH")
                if not trash_pos: return
                tx, ty = trash_pos
                if self.move_towards(controller, bot_id, tx, ty):
                    item = bot_info["holding"]
                    if controller.trash(bot_id, tx, ty):
                        if item["type"] == "Food":
                            self.current_order["required"].append(item.food_name)
                        elif item["type"] == "Plate":
                            self.state = States.PLACE_PLATE
                        else:
                            self.state = States.INIT #restart
        elif self.state == States.NOTHING:
            for i in range(len(my_bots)):
                self.my_bot_id = my_bots[i]
                bot_id = self.my_bot_id
                
                bot_info = controller.get_bot_state(bot_id)
                bx, by = bot_info['x'], bot_info['y']

                dx = random.choice([-1, 1])
                dy = random.choice([-1, 1])
                nx,ny = bx + dx, by + dy
                if controller.can_move(bot_id, nx, ny):
                    controller.move(bot_id, nx, ny)
                    return