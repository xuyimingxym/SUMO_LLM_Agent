import os
import sys
from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import traci
import time
import threading
import randomTrips
import random

if "SUMO_HOME" in os.environ:
    tools_path = os.path.join(os.environ["SUMO_HOME"], "tools")
    sys.path.append(tools_path)

import osmWebWizard
import osmGet
import osmBuild

from agents import Agent, Runner, FunctionTool, RunContextWrapper, function_tool



app = Flask(__name__)
app.config['SECRET_KEY'] = 'a9c20aca683290e004b752a4'
socketio = SocketIO(app, async_mode='threading')

# Configurations
SUMO_BINARY = "sumo"  # or sumo-gui
SUMO_CFG_FILE = "osm.sumocfg"  

sumo_thread = None  
simulation_running = False  
simulation_paused = False  
simulation_results_history = []
simulation_speed = 0.1  # Default sleep time (100 ms)

@socketio.on('update_simulation_speed')
def handle_update_simulation_speed(data):
    global simulation_speed
    simulation_speed = data['speed'] / 1000  # Convert ms to seconds

simulation_duration = 600  # Default total simulation time in seconds

@socketio.on('update_simulation_duration')
def handle_update_simulation_duration(data):
    global simulation_duration
    simulation_duration = data['duration']


def sumo_simulation():
    """
    Run the SUMO simulation and emit vehicle data to the frontend.
    """
    global simulation_running, simulation_paused, simulation_speed, simulation_duration
    traci.start([SUMO_BINARY, "-c", SUMO_CFG_FILE])
    simulation_running = True
    start_time = time.time()
    start_sumo_time = traci.simulation.getTime()
    total_delay = 0
    total_vehicles_inserted = 0

    while simulation_running and traci.simulation.getMinExpectedNumber() > 0:
        current_sumo_time = traci.simulation.getTime()
        # Stop if SUMO time exceeds user-defined duration
        if current_sumo_time - start_sumo_time >= simulation_duration:
            break  

        if simulation_paused:
            time.sleep(0.1)  # Pause loop but keep checking
            continue  

        traci.simulationStep()

        vehicles = []
        for vehicle_id in traci.vehicle.getIDList():
            position = traci.vehicle.getPosition(vehicle_id)
            gps_position = traci.simulation.convertGeo(*position)
            angle = traci.vehicle.getAngle(vehicle_id)
            vehicles.append({'id': vehicle_id, 'x': gps_position[0], 'y': gps_position[1], 'angle': angle})

        socketio.emit('update', vehicles)

        vehicle_count = traci.vehicle.getIDCount()
        vehicle_ids = traci.vehicle.getIDList()
        overall_delay = sum(traci.vehicle.getAccumulatedWaitingTime(vid) for vid in vehicle_ids)
        if vehicle_count > 0:
            average_speed = sum(traci.vehicle.getSpeed(vid) for vid in vehicle_ids) / vehicle_count
            average_delay = overall_delay / vehicle_count
        else:
            average_speed = 0.0
            average_delay = 0.0
        current_sumo_time = traci.simulation.getTime()
        stats = {
            "vehicle_count": vehicle_count,
            "average_speed": average_speed,
            "average_delay": average_delay,
            "overall_delay": overall_delay,
            "simulation_time": current_sumo_time - start_sumo_time
        }
        
        socketio.emit('update_stats', stats)

        total_delay += overall_delay
        total_vehicles_inserted += traci.simulation.getDepartedNumber()

        time.sleep(simulation_speed)

    
    simulation_running = False
    end_time = time.time()

    # Extracting statistics
    simulation_time = traci.simulation.getTime()
    duration = round(end_time - start_time, 2)
    total_delay = total_delay / simulation_time
    delay_per_vehicle = total_delay / total_vehicles_inserted if total_vehicles_inserted > 0 else 0

    results = {
        "Simulation Ended At": f"{simulation_time:.2f}",
        "Simulation Duration": f"{duration} s",
        "Vehicles Inserted": total_vehicles_inserted,
        "Average Speed": f"{round(average_speed, 2)} m/s",
        "Total Delay": f"{total_delay:.2f} s",
        "Delay per Vehicle": f"{delay_per_vehicle:.2f} s",
    }
    simulation_results_history.append(results)

    traci.close()
    socketio.emit('clear_map')
    socketio.emit('simulation_results', results)  # Send results to frontend
    
    
def run_simulation_from_params(volume: int, sim_duration: int, fringe_factor: float, min_distance: int, random_seed: int):
    global sumo_thread, simulation_running, simulation_duration
    if simulation_running:
        return "Simulation already running."
    
    simulation_duration = sim_duration

    route_file = "randomroutes.rou.xml"
    trips_file = "trips.trips.xml"
    net_file = "osm_network/osm.net.xml.gz"

    args = [
        "-n", net_file,
        "-o", trips_file,
        "-r", route_file,
        "--insertion-density", str(volume),
        "-e", sim_duration,
        "--lanes", "--length",
        "--prefix", "veh",
        "--fringe-factor", fringe_factor,
        "--allow-fringe.min-length", 1000,
        "--via-edge-types", "highway.motorway,highway.motorway_link,highway.trunk_link,highway.primary_link,highway.secondary_link,highway.tertiary_link",
        "--seed", random_seed,
        "--random",
        "--min-distance", min_distance,
        "--min-distance.fringe", 10,
        "--remove-loops",
        "--validate",
        "--random-depart",
        "--trip-attributes", 'departLane="best" departPos="random" arrivalPos="random" type="rerouting"',
        "--fringe-start-attributes", 'departSpeed="max"'
    ]
    if os.path.exists(trips_file):
        os.remove(trips_file)

    options = randomTrips.get_options(args)
    randomTrips.main(options)

    simulation_running = True
    sumo_thread = threading.Thread(target=sumo_simulation)
    sumo_thread.start()
    return "Simulation started."


@socketio.on('start_simulation')
def handle_start_simulation(data):
    volume = data.get("volume", 200)
    sim_duration = data.get("sim_duration", 3600)
    fringe_factor = data.get("fringe_factor", 1)
    min_distance = data.get("min_distance", 300)
    random_seed = data.get("random_seed", 1234)

    run_simulation_from_params(
        volume=volume,
        sim_duration=sim_duration,
        fringe_factor=fringe_factor,
        min_distance=min_distance,
        random_seed=random_seed
    )


@function_tool
def start_simulation_agent(
    volume: int,
    sim_duration: int,
    fringe_factor: float,
    min_distance: int,
    random_seed: int
) -> str:
    """
    Starts a SUMO simulation with the given parameters (LLM callable version).
    """
    return run_simulation_from_params(
        volume=volume,
        sim_duration=sim_duration,
        fringe_factor=fringe_factor,
        min_distance=min_distance,
        random_seed=random_seed
    )


@function_tool
@socketio.on('pause_simulation')
def handle_pause_simulation():
    """
    Pause the simulation.
    """
    global simulation_paused
    simulation_paused = True
    # emit('simulation_status', {'message': 'Simulation paused'})

@function_tool
@socketio.on('resume_simulation')
def handle_resume_simulation():
    """
    Resume the simulation.
    """
    global simulation_paused
    simulation_paused = False
    # emit('simulation_status', {'message': 'Simulation resumed'})

@function_tool
@socketio.on('stop_simulation')
def handle_stop_simulation():
    """
    Stop the simulation.
    """
    global simulation_running
    simulation_running = False
    # emit('simulation_status', {'message': 'Simulation stopped'})

@function_tool
@socketio.on('request_traffic_volume')
def handle_traffic_volume_request():
    """
    Get traffic volume data for each edge in the simulation.
    """
    edges_volume = []

    for edge_id in traci.edge.getIDList():
        volume = traci.edge.getLastStepVehicleNumber(edge_id)

        # Get the shape of the first lane of the edge
        lane_id = f"{edge_id}_0"  # First lane of the edge
        if lane_id in traci.lane.getIDList():
            shape = traci.lane.getShape(lane_id)

            # Compute edge length
            total_length = sum(
                ((shape[i+1][0] - shape[i][0])**2 + (shape[i+1][1] - shape[i][1])**2) ** 0.5
                for i in range(len(shape) - 1)
            )

            # Convert shape to GPS coordinates and filter out short edges
            if total_length >= 15:
                gps_shape = [traci.simulation.convertGeo(*point) for point in shape]
                edges_volume.append({
                    'id': edge_id,
                    'volume': volume,
                    'shape': gps_shape
                })

    emit('traffic_volume_data', edges_volume)

@function_tool
@socketio.on('request_traffic_speed')
def handle_traffic_speed_request():
    """
    Get average speed data for each edge in the simulation.
    """
    edges_speed = []

    for edge_id in traci.edge.getIDList():
        avg_speed = traci.edge.getLastStepMeanSpeed(edge_id)  # Get avg speed of vehicles on edge

        # Get the shape of the first lane of the edge
        lane_id = f"{edge_id}_0"
        if lane_id in traci.lane.getIDList():
            shape = traci.lane.getShape(lane_id)

            # Compute edge length
            total_length = sum(
                ((shape[i+1][0] - shape[i][0])**2 + (shape[i+1][1] - shape[i][1])**2) ** 0.5
                for i in range(len(shape) - 1)
            )

            # Convert shape to GPS coordinates and filter out short edges
            if total_length >= 15:
                gps_shape = [traci.simulation.convertGeo(*point) for point in shape]
                edges_speed.append({
                    'id': edge_id,
                    'speed': avg_speed,
                    'shape': gps_shape
                })

    emit('traffic_speed_data', edges_speed)

@function_tool
@socketio.on('request_fuel_consumption')
def handle_fuel_consumption_request():
    """
    Get fuel consumption data for each edge in the simulation.
    """
    edges_fuel = []

    for edge_id in traci.edge.getIDList():
        fuel_consumption = traci.edge.getFuelConsumption(edge_id)  # Get fuel consumption

        # Get the shape of the first lane of the edge
        lane_id = f"{edge_id}_0"
        if lane_id in traci.lane.getIDList():
            shape = traci.lane.getShape(lane_id)

            # Compute edge length
            total_length = sum(
                ((shape[i+1][0] - shape[i][0])**2 + (shape[i+1][1] - shape[i][1])**2) ** 0.5
                for i in range(len(shape) - 1)
            )

            # Convert shape to GPS coordinates and filter out short edges
            if total_length >= 15:
                gps_shape = [traci.simulation.convertGeo(*point) for point in shape]
                edges_fuel.append({
                    'id': edge_id,
                    'fuel': fuel_consumption,
                    'shape': gps_shape
                })

    emit('fuel_consumption_data', edges_fuel)

@function_tool
@socketio.on('request_noise_emission')
def handle_noise_emission_request():
    """
    Get noise emission data for each edge in the simulation.
    """
    edges_noise = []

    for edge_id in traci.edge.getIDList():
        noise_emission = traci.edge.getNoiseEmission(edge_id)  # Get noise emission

        # Get the shape of the first lane of the edge
        lane_id = f"{edge_id}_0"
        if lane_id in traci.lane.getIDList():
            shape = traci.lane.getShape(lane_id)

            # Compute edge length
            total_length = sum(
                ((shape[i+1][0] - shape[i][0])**2 + (shape[i+1][1] - shape[i][1])**2) ** 0.5
                for i in range(len(shape) - 1)
            )

            # Convert shape to GPS coordinates and filter out short edges
            if total_length >= 15:
                gps_shape = [traci.simulation.convertGeo(*point) for point in shape]
                edges_noise.append({
                    'id': edge_id,
                    'noise': noise_emission,
                    'shape': gps_shape
                })

    emit('noise_emission_data', edges_noise)

@socketio.on('generate_network')
def handle_generate_network(data):
    bbox = data.get("bbox")
    output_dir = data.get("output_dir", "osm_network")
    prefix = data.get("prefix", "osm")

    if not bbox:
        emit("network_generation_status", {"status": "error", "message": "No bounding box provided."})
        return

    try:
        thread = threading.Thread(
            target=lambda: _run_osm_pipeline(bbox, output_dir, prefix)
        )
        thread.start()

        emit("network_generation_status", {"status": "started"})
    except Exception as e:
        emit("network_generation_status", {"status": "error", "message": str(e)})

def _run_osm_pipeline(bbox, output_dir, prefix):
    try:
        # Step 1: Download OSM data
        print('osmGet strat...')
        osm_args = ["-b=" + bbox, "-d", output_dir, "-z"]
        osmGet.get(osm_args)
        print('osmGet done...')

        # Step 2: Build SUMO network
        print('osmBuild strat...')
        osm_file = os.path.join(output_dir, f"{prefix}_bbox.osm.xml.gz")
        build_args = [
            "-f", osm_file,
            "-d", output_dir,
            "--vehicle-classes", "passenger",
            "-z"
        ]
        osmBuild.build(build_args)
        print('osmBuild done...')

        socketio.emit("network_generation_status", {"status": "completed"})

    except Exception as e:
        socketio.emit("network_generation_status", {"status": "error", "message": str(e)})   

@socketio.on("request_sumo_network")
def handle_request_sumo_network():
    import sumolib
    import gzip

    net_file = "osm_network/osm.net.xml.gz"

    try:
        net = sumolib.net.readNet(net_file)
        
        # features = []
        # for edge in net.getEdges():
        #     shape = edge.getShape()
        #     if len(shape) > 1:
        #         coords = [net.convertXY2LonLat(x, y) for x, y in shape]
        #         features.append({
        #             "type": "Feature",
        #             "geometry": {
        #                 "type": "LineString",
        #                 "coordinates": coords
        #             },
        #             "properties": {
        #                 "id": edge.getID(),
        #                 "from": edge.getFromNode().getID() if edge.getFromNode() else "",
        #                 "to": edge.getToNode().getID() if edge.getToNode() else "",
        #                 "speed": edge.getSpeed(),
        #                 "length": edge.getLength()
        #             }
        #         })
        features = []
        for lane_id, shape, width in net.getGeometries(useLanes=True, includeJunctions=True):
            coords = [net.convertXY2LonLat(x, y) for x, y in shape]
            if len(coords) > 1:
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": coords
                    },
                    "properties": {
                        "lane_id": lane_id,
                        "width": width
                    }
                })

        geojson = {
            "type": "FeatureCollection",
            "features": features
        }

        emit("sumo_network_geojson", geojson)

    except Exception as e:
        emit("sumo_network_error", {"error": str(e)})

@socketio.on('close_random_edge')
def handle_close_random_edge():
    if not simulation_running:
        return
    try:
        edge_ids = traci.edge.getIDList()
        if edge_ids:
            edge_to_close = random.choice(edge_ids)
            traci.edge.setDisallowed(edge_to_close, ["passenger"])

            # Reroute all vehicles currently in simulation
            for vehicle_id in traci.vehicle.getIDList():
                traci.vehicle.rerouteTraveltime(vehicle_id)

            # Visualize first lane of the closed edge
            first_lane_id = f"{edge_to_close}_0"
            if first_lane_id in traci.lane.getIDList():
                shape = traci.lane.getShape(first_lane_id)
                gps_shape = [traci.simulation.convertGeo(x, y) for x, y in shape]

                emit('highlight_closed_edge', {
                    'edge_id': edge_to_close,
                    'shape': gps_shape
                })

        print(f"Closed edge: {edge_to_close}")
    except Exception as e:
        emit('simulation_status', {'message': f'Error closing edge: {str(e)}'})
        
@function_tool
def get_simulation_summary(n: int) -> str:
    """
    Get the last n simulation results from the history.
    """
    if not simulation_results_history:
        return "No simulation history found yet."

    n = min(n, len(simulation_results_history))
    summaries = simulation_results_history[-n:]

    response = f"Showing the last {n} simulation(s):\n\n"
    for i, result in enumerate(reversed(summaries), 1):
        response += f"--- Simulation #{len(simulation_results_history) - i + 1} ---\n"
        for key, value in result.items():
            response += f"{key}: {value}\n"
        response += "\n"

    return response.strip()


# @socketio.on('close_random_lane')
# def handle_close_random_lane():
#     if not simulation_running:
#         return
#     try:
#         lane_ids = traci.lane.getIDList()
#         if lane_ids:
#             lane_to_close = random.choice(lane_ids)
#             traci.lane.setDisallowed(lane_to_close, ["passenger"])
#             shape = traci.lane.getShape(lane_to_close)
#             gps_shape = [traci.simulation.convertGeo(x, y) for x, y in shape]

#             print(f"Closed lane: {lane_to_close}")
#             emit('highlight_closed_lane', {
#                 'lane_id': lane_to_close,
#                 'shape': gps_shape
#             })
#     except Exception as e:
#         emit('simulation_status', {'message': f'Error closing lane: {str(e)}'})

######
# traffic light change
######

@function_tool
def get_traffic_light_ids() -> str:
    """
    Returns a list of all traffic light IDs in the current SUMO network.
    """
    try:
        ids = traci.trafficlight.getIDList()
        if not ids:
            return "No traffic lights found in the current simulation."
        return "Available traffic light IDs: " + ", ".join(ids)
    except Exception as e:
        return f"Error fetching traffic lights: {e}"

@function_tool
def set_traffic_light_state(tl_id: str, state: str) -> str:
    try:
        current_state = traci.trafficlight.getRedYellowGreenState(tl_id)
        if len(state) != len(current_state):
            return (
                f"State length mismatch for TLS {tl_id}. "
                f"Expected {len(current_state)} characters, got {len(state)}."
            )
        
        traci.trafficlight.setRedYellowGreenState(tl_id, state)
        return f"Traffic light {tl_id} state set to {state}."
    except Exception as e:
        return f"Failed to set traffic light state for {tl_id}: {e}"


@function_tool
def reset_all_traffic_lights_to_auto() -> str:
    """
    Reset all traffic lights to their default automatic program.
    """
    try:
        for tl_id in traci.trafficlight.getIDList():
            traci.trafficlight.setProgram(tl_id, "0")  
        return "All traffic lights set to automatic mode."
    except Exception as e:
        return f"Error: {e}"

@function_tool
def get_tls_phase_structure(tls_id: str) -> str:
    """
    Returns a summary of the phase structure of a traffic light system.
    Includes phase duration, signal pattern, and valid state length.
    """

    import traci

    try:
        definitions = traci.trafficlight.getCompleteRedYellowGreenDefinition(tls_id)
        if not definitions:
            return f"No traffic light definition found for ID '{tls_id}'."

        definition = definitions[0]
        summary = [f"Traffic Light ID: {tls_id}", f"Program ID: {definition.programID}", "Phases:"]

        for i, phase in enumerate(definition.phases):
            summary.append(
                f"  Phase {i}: duration={phase.duration}s, minDur={phase.minDur}, maxDur={phase.maxDur}, state='{phase.state}'"
            )

        summary.append(f"\nState string length = {len(definition.phases[0].state)} (this is required when setting new light states)")

        return "\n".join(summary)

    except Exception as e:
        return f"Error while retrieving traffic light phases for '{tls_id}': {e}"


####
# Agent traffic light optimization
####




agent = Agent(
    name="Assistant",
    instructions="""
        You are a traffic simulation assistant that helps users run and analyze simulations powered by the SUMO engine.

        You have access to tools that can:
        - start, pause, resume, or stop a simulation with custom parameters,
        - retrieve metrics such as traffic speed, volume, noise, and fuel consumption,
        - and summarize results from previously completed simulations.

        **Important instructions**:
        - When starting a simulation, if any parameters are missing, you may use your own value. But you must always state the values you used in your response.
        - Do not assume user intent. Always clarify ambiguous requests.
        - Respond concisely but informatively, and avoid hallucinating capabilities that are not implemented.
        - Always call get_traffic_light_ids before modifying traffic lights.

        Only operate on the currently loaded SUMO network. You do not manage or generate road networks.

        Your goal is to help the user interact with the traffic simulation effectively and transparently.

    """,
    tools=[
            start_simulation_agent, 
            handle_pause_simulation, 
            handle_resume_simulation, 
            handle_stop_simulation, 
            # handle_traffic_volume_request, 
            # handle_traffic_speed_request, 
            # handle_fuel_consumption_request, 
            # handle_noise_emission_request,
            get_simulation_summary,
            set_traffic_light_state,
            reset_all_traffic_lights_to_auto,
            get_traffic_light_ids,
            get_tls_phase_structure,
           ],  
    model="gpt-4o",
)
conversation_history = []

@socketio.on('agent_execute')
def handle_agent_execute(data):
    global conversation_history
    user_input = data.get("params", "")

    # Append user message
    conversation_history.append({"role": "user", "content": user_input})

    try:
        result = asyncio.run(Runner.run(
            agent,
            input=conversation_history  
        ))

        assistant_reply = result.final_output
        conversation_history.append({"role": "assistant", "content": assistant_reply})
        
        socketio.emit('agent_response', {'response': assistant_reply})

    except Exception as e:
        socketio.emit('agent_response', {'response': f"Error: {e}"})



@app.route('/')
def index():
    return render_template('index.html', mapbox_token="pk.eyJ1IjoieHlteHV5aW1pbmciLCJhIjoiY2x1MzRid2RkMHpzbzJpbnlkMWlzaTE5eSJ9.drFEvv4Uogi-69W_owAQog")


import asyncio

@socketio.on('request_simulation_history')
def handle_simulation_history():
    """
    Return the last 5 simulation results in a formatted way.
    """
    if not simulation_results_history:
        socketio.emit('simulation_history', {
            'history': [],
            'message': 'No simulation history available.'
        })
        return

    last_5_results = simulation_results_history[-5:]
    formatted_results = []
    
    for i, result in enumerate(last_5_results, 1):
        formatted_result = {
            'id': len(simulation_results_history) - len(last_5_results) + i,
            'time': result.get('Simulation Ended At', 'N/A'),
            'duration': result.get('Simulation Duration', 'N/A'),
            'vehicles': result.get('Vehicles Inserted', 'N/A'),
            'avg_speed': result.get('Average Speed', 'N/A'),
            'total_delay': result.get('Total Delay', 'N/A'),
            'delay_per_vehicle': result.get('Delay per Vehicle', 'N/A')
        }
        formatted_results.append(formatted_result)

    socketio.emit('simulation_history', {
        'history': formatted_results,
        'message': 'Success'
    })

if __name__ == "__main__":
    socketio.run(app, debug=True, host="0.0.0.0")
