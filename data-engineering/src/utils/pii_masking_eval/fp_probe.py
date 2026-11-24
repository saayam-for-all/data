"""Extra false-positive stress probe: clean texts written AFTER rules were frozen, chosen to resemble cue patterns."""
import importlib.util, os, sys
def load(n):
    s=importlib.util.spec_from_file_location(n,os.path.join(os.path.dirname(os.path.abspath(__file__)),n+".py"));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
D=load("detectors")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
rx=D.build_lookup_regex(D.load_name_lookup(sys.argv[1]))
P=["Help Wanted: need someone to fix a leaking sink.","Please call Monday morning to confirm the pickup time.",
"Need a ride from Tempe Public Library to Mesa Community College.","Contact the Housing Authority about the notice.",
"Ride for Grandma to Banner Hospital on Tuesday.","Dear Volunteers, thank you for the groceries last week.",
"Thanks, that really helped us.","This is Urgent, the heater is broken.","Mondays work. Call after noon.",
"Help Seniors in Need of winter blankets.","From Tempe to Mesa, 3 passengers.","I'm Hungry and out of food until Friday.",
"Contact Lenses needed for my son, prescription is expired.","Call Center job application help, resume formatting.",
"My neighbor Needs Help getting to church.","Looking for Spanish Speaking volunteers for Saturday.",
"Need help with FAFSA and Pell Grant forms for my daughter.","Please help with Section 8 housing paperwork.",
"It's Thanksgiving week and we need a turkey and sides.","Ask for the Front Desk Manager when you arrive.",
"Bus route 72 from 5th Street to University Drive.","I need a ride to the DMV on 3rd Avenue next Wednesday at 10."]
fp=0
for t in P:
    sp=D.detect_layered(t,rx)
    if sp: fp+=1; print("FP:",t,"->",[t[s:e] for s,e,_ in sp])
print("false positives",fp,"of",len(P))
