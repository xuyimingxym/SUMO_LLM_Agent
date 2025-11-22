# command line:
python randomTrips.py -n osm.net.xml.gz --prefix veh --vehicle-class passenger --lanes --length --fringe-factor 5 --allow-fringe.min-length 1000 --via-edge-types highway.motorway,highway.motorway_link,highway.trunk_link,highway.primary_link,highway.secondary_link,highway.tertiary_link --seed 1234 --random --min-distance 300 --min-distance.fringe 10 --remove-loops --validate --insertion-density 600 --random-depart -e 3600 -r randomroutes.rou.xml
--trip-attributes departLane="best" --fringe-start-attributes departSpeed="max"

# Settings:
- "-n NETFILE": define the net file (mandatory)
- "-r ROUTEFILE": generates route file with duarouter
- "--prefix TRIPPREFIX": prefix for the trip ids
- "--trip-attributes departLane=&quot;best&quot;": additional trip attributes
- "--fringe-start-attributes departSpeed=&quot;max&quot;": additional trip attributes when starting on a fringe.
- "--vehicle-class passenger": The vehicle class assigned to the generated trips (adds a standard vType definition to the output file)
- "--lanes": weight edge probability by number of lanes
- "--length": weight edge probability by length
- "--fringe-factor 5": multiply weight of fringe edges by 'FLOAT' (default 1) or set value 'max' to force all traffic to start/end at the fringe.
- "--allow-fringe.min-length 1000": Allow departing on edges that leave the network and arriving on edges that enter the network, if they have at least the given length
- "--via-edge-types highway.motorway,highway.motorway_link,highway.trunk_link,highway.primary_link,highway.secondary_link,highway.tertiary_link": Set list of edge types that cannot be used for departure or arrival (unless being on the fringe)
- "--seed 1234": random seed;
- "--random": use a random seed to initialize the random number generator
- "--min-distance 300": require start and end edges for each trip to be at least 'FLOAT' m apart
- "--min-distance.fringe 10": require start and end edges for each fringe to fringe trip to be at least 'FLOAT' m apart
- "--remove-loops True": Remove loops at route start and end
- "--validate True": Whether to produce trip output that is already checked for connectivity
- "--insertion-density FLOAT": How much vehicles arrive in the simulation per hour per kilometer of road (alternative to the period option).
- "--random-depart": Distribute departures randomly between begin and end
- "-e END": end time (default 3600)

# Inlcude in Web
- "--fringe-factor 5"
- "seed 1234"
- "--min-distance 300"
- "--insertion-density FLOAT"
- 
