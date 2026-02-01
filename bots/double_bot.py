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
        # self.my_bot_id = None
        self.current_order = {}
        self.b_pos_x = {}
        self.b_pos_y = {}
        self.orders = None
        self.nextMove = {}

        self.tile_cache = {}
        self._build_tile_cache()

        self.path_cache = {}  # Cache computed paths
        self.cache_hits = 0
        self.cache_misses = 0

        self.state = {}

    def get_bfs_path(
        self,
        controller: RobotController,
        start: Tuple[int, int],
        target: Tuple[int, int],
        bot_id: int
    ) -> Optional[Tuple[int, int]]:

        if not hasattr(self, "avoid_pos"):
            self.avoid_pos = {}

        avoid = self.avoid_pos.get(bot_id)

        obstacles = set()
        for k in self.b_pos_x:
            if k != bot_id:
                ox, oy = self.b_pos_x[k], self.b_pos_y[k]
                if ox is not None:
                    obstacles.add((ox, oy))

        queue = deque([(start, [])])
        visited = {start}
        w, h = self.map.width, self.map.height

        directions = [
            (0, 0),
            (0, -1), (0, 1), (-1, 0), (1, 0),
            (-1, -1), (-1, 1), (1, -1), (1, 1)
        ]

        while queue:
            (cx, cy), path = queue.popleft()

            if max(abs(cx - target[0]), abs(cy - target[1])) <= 1:
                return path[0] if path else (0, 0)

            for dx, dy in directions:
                nx, ny = cx + dx, cy + dy

                if not (0 <= nx < w and 0 <= ny < h):
                    continue
                if (nx, ny) in visited:
                    continue
                if (nx, ny) in obstacles:
                    continue
                if not self.map.tiles[nx][ny].is_walkable:
                    continue

                # 🚫 avoid forced-reverse tile
                if avoid and (nx, ny) == avoid:
                    continue

                visited.add((nx, ny))
                queue.append(((nx, ny), path + [(dx, dy)]))

        return None
    
    def move_towards(self, controller: RobotController, bot_id: int, target_x: int, target_y: int) -> bool:
        bot_state = controller.get_bot_state(bot_id)
        bx, by = bot_state['x'], bot_state['y']
        
        # Update position
        self.b_pos_x[bot_id] = bx
        self.b_pos_y[bot_id] = by
        
        # Already adjacent
        if max(abs(bx - target_x), abs(by - target_y)) <= 1:
            return True
        
        step = self.get_bfs_path(controller, (bx, by), (target_x, target_y), bot_id)
        
        # If no path found, wait (don't move)
        if not step or step == (0, 0):
            return False
        
        # Check if the next step is occupied by another bot
        next_x, next_y = bx + step[0], by + step[1]
        for k in self.b_pos_x.keys():
            if k != bot_id:
                if self.b_pos_x[k] == next_x and self.b_pos_y[k] == next_y:
                    # Another bot is in the way, wait
                    return False
        
        # Safe to move
        self.b_pos_x[bot_id] = next_x
        self.b_pos_y[bot_id] = next_y
        controller.move(bot_id, step[0], step[1])
        return False


    # def move_towards(self, controller: RobotController, bot_id: int, target_x: int, target_y: int) -> bool:
    #     bot_state = controller.get_bot_state(bot_id)
    #     bx, by = bot_state['x'], bot_state['y']
        
    #     # Check if already adjacent
    #     if max(abs(bx - target_x), abs(by - target_y)) <= 1:
    #         return True
        
    #     step = self.get_bfs_path(controller, (bx, by), (target_x, target_y))
    #     if step and step != (0, 0):
    #         self.nextMove[bot_id] = (step[0], step[1])
    #         controller.move(bot_id, step[0], step[1])
    #         return False
    #     return False

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
    
    def process_orders(self, controller: RobotController):
        self.orders = []
        orders = controller.get_orders(controller.get_team())
        # print("Raw Orders: ", orders)
        current_turn = controller.get_turn()
        for order in orders:
            if order['is_active'] == False or order['claimed_by'] != None: continue
            reward = order['reward']
            penalty = order['penalty']
            cost = 0
            est_time = 0
            for food in order['required']:
                cost += FoodType[food].buy_cost
                est_time += FoodType[food].can_cook * 20 + FoodType[food].can_chop * 2 + 5
            
            time_remaining = order['expires_turn'] - current_turn
            time_buffer = time_remaining - est_time
            
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

    # def play_turn(self, controller: RobotController):
    #     my_bots = controller.get_team_bot_ids(controller.get_team())
    #     if not my_bots: return
    
    #     # self.my_bot_id = my_bots[0]
    #     # bot_id = self.my_bot_id
        
    #     # tmp_orders = controller.get_orders(controller.get_team())
    #     # print("tmp_orders: ", tmp_orders)
    #     # for order in tmp_orders:
    #     #     print("order: ", order["order_id"])
    #     #     if self.current_order_b1 and order["order_id"] == self.current_order_b1["order_id"] and order["is_active"] == False:
    #     #         self.current_order_b1 = None
    #     #     if self.current_order_b2 and order["order_id"] == self.current_order_b2["order_id"] and order["is_active"] == False:
    #     #         self.current_order_b2 = None

    #     # self.orders = controller.get_orders(controller.get_team())
    #     for bot_id, bot_order in enumerate(self.current_order):
    #         if bot_order is None: 
    #             self.process_orders(controller)
    #             # print("orders: ", self.orders)
    #             for order in self.orders:
    #                 for assigned_order in self.current_order:
    #                     if assigned_order is not None and order["order_id"] == assigned_order["order_id"]:
    #                         break
    #                 else:
    #                     self.current_order[bot_id] = order
    #                     print("assigned order: ", order)
    #                     print("bot_id: ", bot_id)
        
    #     # raise Exception("test")
    #     #         self.current_order[bot_id] = self.orders[0] if len(self.orders) > 0 and self.else None
    #     #     if bot_order["is_active"] == False:
    #     #         self.current_order.remove(bot_order)
    #     # if(not self.current_order_b1 or not self.current_order_b2):
    #     #     # if self.orders is None:
    #     #     self.process_orders(controller)
    #     #     # else:
    #     #     #     self.update_orders(controller)
    #     #     self.current_order_b1 = self.orders[0] if len(self.orders) > 0 else None
    #     #     self.current_order_b2 = self.orders[1] if len(self.orders) > 1 else None
        
    #     self.run_game(controller, my_bots[0])
    #     self.run_game(controller, my_bots[1])
    #         # for order in self.orders:
    #         #     # print("Check: ", order["claimed_by"])
    #         #     # print(order)
    #         #     if order["claimed_by"] is None:
    #         #         self.current_order = order
    #         #         print(self.current_order)
    #         #         print(controller.get_turn())
    #         #         break
    def play_turn(self, controller: RobotController):
        my_bots = controller.get_team_bot_ids(controller.get_team())
        if not my_bots: return

        # Initialize state for new bots
        for bot_id in my_bots:
            if bot_id not in self.state:
                self.state[bot_id] = States.INIT
                self.current_order[bot_id] = None
                self.b_pos_x[bot_id] = None
                self.b_pos_y[bot_id] = None
        
        # Assign orders to bots that don't have one
        for bot_id in my_bots:
            if self.current_order.get(bot_id) is None:
                self.process_orders(controller)
                
                # Get list of already assigned order IDs
                assigned_order_ids = set()
                for bid in my_bots:
                    if bid in self.current_order and self.current_order[bid] is not None:
                        assigned_order_ids.add(self.current_order[bid]["order_id"])
                
                # Find an unassigned order
                for order in self.orders:
                    if order["order_id"] not in assigned_order_ids:
                        self.current_order[bot_id] = order
                        print(f"assigned order {order['order_id']} to bot {bot_id}")
                        break
        
        # Run each bot
        for bot_id in my_bots:
            self.run_game(controller, bot_id)

    def run_game(self, controller: RobotController, bot_id: int):

        # my_bots = controller.get_team_bot_ids(controller.get_team())
        # if not my_bots: return
    
        # self.my_bot_id = my_bots[0]
        # bot_id = self.my_bot_id

        # # self.orders = controller.get_orders(controller.get_team())
        # if(not self.current_order):
        #     # if self.orders is None:
        #     self.process_orders(controller)
        #     # else:
        #     #     self.update_orders(controller)
        #     for order in self.orders:
        #         # print("Check: ", order["claimed_by"])
        #         # print(order)
        #         if order["claimed_by"] is None:
        #             self.current_order = order
        #             print(self.current_order)
        #             print(controller.get_turn())
        #             break
        
        
        bot_info = controller.get_bot_state(bot_id)
        bx, by = bot_info['x'], bot_info['y']
        self.b_pos_x[bot_id] = bx
        self.b_pos_y[bot_id] = by

        if self.assembly_counter is None:
            self.assembly_counter = self.find_nearest_tile(controller, bx, by, "COUNTER")
        if self.cooker_loc is None:
            self.cooker_loc = self.find_nearest_tile(controller, bx, by, "COOKER")
        if self.submit_pos is None:
            self.submit_pos = self.find_nearest_tile(controller, bx, by, "SUBMIT")
        if self.sink_pos is None:
            self.sink_pos = self.find_nearest_tile(controller, bx, by, "SINK")
        if self.sinktable_pos is None:
            self.sinktable_pos = self.find_nearest_tile(controller, bx, by, "SINKTABLE")

        if not self.assembly_counter or not self.cooker_loc or not self.submit_pos: 
            return

        cx, cy = self.assembly_counter
        kx, ky = self.cooker_loc
        ux, uy = self.submit_pos
        wx, wy = self.sink_pos
        stx, sty = self.sinktable_pos

        # if self.state[bot_id] in [2, 8, 10] and bot_info.get('holding'):
        #     self.state[bot_id] = 16

        #state 0: init + checking the pan
            
        if bot_id not in self.state:
            self.state[bot_id] = States.INIT
        
        if self.current_order[bot_id] is not None and self.state[bot_id] == States.NOTHING:
            self.state[bot_id] = States.INIT

        if self.state[bot_id] == States.INIT:
            if(not self.current_order[bot_id]):
                self.state[bot_id] = States.NOTHING
            else:
                kTile = controller.get_tile(controller.get_team(), kx, ky)
                uTile = controller.get_tile(controller.get_team(), ux, uy)
                if kTile and isinstance(kTile.item, Pan) and uTile and isinstance(uTile.item, Plate):
                    self.state[bot_id] = States.BUY_FOOD
                elif kTile and isinstance(kTile.item, Pan):
                    self.state[bot_id] = States.BUY_PLATE
                else:
                    self.state[bot_id] = States.BUY_PAN

        elif self.state[bot_id] == States.BUY_PAN:
            holding = bot_info.get('holding')
            if holding: # check if it is a pan if needed
                if self.move_towards(controller, bot_id, kx, ky):
                    if controller.place(bot_id, kx, ky):
                        self.state[bot_id] = States.INIT
            else:
                shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
                if not shop_pos: return
                sx, sy = shop_pos
                if self.move_towards(controller, bot_id, sx, sy):
                    if controller.get_team_money(controller.get_team()) >= ShopCosts.PAN.buy_cost:
                        controller.buy(bot_id, ShopCosts.PAN, sx, sy)

        elif self.state[bot_id] == States.BUY_FOOD:
            if len(self.current_order[bot_id]["required"]) == 0:
                self.state[bot_id] = States.SUBMIT
            else:
                shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
                sx, sy = shop_pos
                if self.move_towards(controller, bot_id, sx, sy):
                    buyFood = self.current_order[bot_id]["required"].pop()
                    if(buyFood == "MEAT"):
                        if controller.get_team_money(controller.get_team()) >= FoodType.MEAT.buy_cost:
                            if controller.buy(bot_id, FoodType.MEAT, sx, sy):
                                self.state[bot_id] = States.PLACE_ON_COUNTER
                    elif(buyFood == "EGG"):
                        if controller.get_team_money(controller.get_team()) >= FoodType.EGG.buy_cost:
                            if controller.buy(bot_id, FoodType.EGG, sx, sy):
                                self.state[bot_id] = States.COOK_FOOD
                    elif(buyFood == "ONIONS"):
                        if controller.get_team_money(controller.get_team()) >= FoodType.ONIONS.buy_cost:
                            if controller.buy(bot_id, FoodType.ONIONS, sx, sy):
                                self.state[bot_id] = States.PLACE_ON_COUNTER
                    elif(buyFood == "NOODLES"):
                        print("checked")
                        if controller.get_team_money(controller.get_team()) >= FoodType.NOODLES.buy_cost:
                            if controller.buy(bot_id, FoodType.NOODLES, sx, sy):
                                self.state[bot_id] = States.ADD_FOOD
                    elif(buyFood == "SAUCE"):
                        if controller.get_team_money(controller.get_team()) >= FoodType.SAUCE.buy_cost:
                            if controller.buy(bot_id, FoodType.SAUCE, sx, sy):
                                self.state[bot_id] = States.ADD_FOOD

        elif self.state[bot_id] == States.PLACE_ON_COUNTER:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.place(bot_id, cx, cy):
                    self.state[bot_id] = States.CHOP_FOOD

        elif self.state[bot_id] == States.CHOP_FOOD:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.chop(bot_id, cx, cy):
                    self.state[bot_id] = States.PICKUP_CHOPPED

        #state 5: pickup meat
        elif self.state[bot_id] == States.PICKUP_CHOPPED:
            if self.move_towards(controller, bot_id, cx, cy):
                if controller.pickup(bot_id, cx, cy):
                    food = controller.get_bot_state(bot_id)["holding"]
                    # print(food)
                    if(food["food_id"] in [0, 2]):
                        self.state[bot_id] = States.COOK_FOOD
                    else:
                        self.state[bot_id] = States.ADD_FOOD

        elif self.state[bot_id] == States.COOK_FOOD:
            if self.move_towards(controller, bot_id, kx, ky):
                # Using the NEW logic where place() starts cooking automatically
                if controller.place(bot_id, kx, ky):
                    self.state[bot_id] = States.WAIT_AND_TAKE

        #state 8: buy the plate
        elif self.state[bot_id] == States.BUY_PLATE:
            shop_pos = self.find_nearest_tile(controller, bx, by, "SHOP")
            sx, sy = shop_pos
            if self.move_towards(controller, bot_id, sx, sy):
                if controller.get_team_money(controller.get_team()) >= ShopCosts.PLATE.buy_cost:
                    if controller.buy(bot_id, ShopCosts.PLATE, sx, sy):
                        self.state[bot_id] = States.PLACE_PLATE

        elif self.state[bot_id] == States.PLACE_PLATE:
            if not bot_info["holding"]:
                controller.pickup(bot_id, bx, by)
            else:
                if self.move_towards(controller, bot_id, ux, uy):
                    if controller.place(bot_id, ux, uy):
                        self.state[bot_id] = States.INIT

        elif self.state[bot_id] == States.ADD_FOOD:
            if self.move_towards(controller, bot_id, ux, uy):
                if controller.add_food_to_plate(bot_id, ux, uy):
                    if self.current_order[bot_id]["expires_turn"] <= controller.get_turn():
                        self.state[bot_id] = States.TRASH
                        self.current_order[bot_id] = None
                    else:
                        self.state[bot_id] = States.INIT

        elif self.state[bot_id] == States.WAIT_AND_TAKE:
            if self.move_towards(controller, bot_id, kx, ky):
                tile = controller.get_tile(controller.get_team(), kx, ky)
                if tile and isinstance(tile.item, Pan) and tile.item.food:
                    food = tile.item.food
                    if food.cooked_stage == 1:
                        if controller.take_from_pan(bot_id, kx, ky):
                            self.state[bot_id] = States.ADD_FOOD
                    elif food.cooked_stage == 2:
                        if controller.take_from_pan(bot_id, kx, ky):
                            self.state[bot_id] = States.TRASH

        elif self.state[bot_id] == States.SUBMIT:
            if self.move_towards(controller, bot_id, ux, uy):
                if not bot_info["holding"]:
                    controller.pickup(bot_id, ux, uy)
                else:
                    if controller.submit(bot_id, ux, uy):
                        self.current_order[bot_id] = None
                        self.state[bot_id] = States.WASH_DISH
                    else:
                        self.state[bot_id] = States.TRASH
        
        elif self.state[bot_id] == States.WASH_DISH:
            if self.move_towards(controller, bot_id, wx, wy):
                st_tile = controller.get_tile(controller.get_team(), stx, sty)

                if st_tile and st_tile.num_clean_plates > 0:
                    self.state[bot_id] = States.GET_PLATE_FROM_SINKTABLE
                else:
                    controller.wash_sink(bot_id, wx, wy)
                    
        
        elif self.state[bot_id] == States.GET_PLATE_FROM_SINKTABLE:
            if self.move_towards(controller, bot_id, stx, sty):
                if controller.take_clean_plate(bot_id, stx, sty):
                    self.state[bot_id] = States.PLACE_PLATE

        elif self.state[bot_id] == States.TRASH:
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
                            self.current_order[bot_id]["required"].append(item.food_name)
                        elif item["type"] == "Plate":
                            self.state[bot_id] = States.PLACE_PLATE
                        else:
                            self.state[bot_id] = States.INIT #restart
        # elif self.state[bot_id] == States.NOTHING:
            # for i in range(len(my_bots)):
            #     self.my_bot_id = my_bots[i]
            #     bot_id = self.my_bot_id
                
            #     bot_info = controller.get_bot_state(bot_id)
            #     bx, by = bot_info['x'], bot_info['y']

            #     dx = random.choice([-1, 1])
            #     dy = random.choice([-1, 1])
            #     nx,ny = bx + dx, by + dy
            #     if controller.can_move(bot_id, nx, ny):
            #         controller.move(bot_id, nx, ny)
            #         return