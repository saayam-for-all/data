"""Fresh probe written after the rules were frozen (not used for tuning)."""
import importlib.util, os, sys
s=importlib.util.spec_from_file_location("d",os.path.join(os.path.dirname(os.path.abspath(__file__)),"detectors.py"));D=importlib.util.module_from_spec(s);s.loader.exec_module(D)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
rx=D.build_lookup_regex(D.load_name_lookup(sys.argv[1]))
CLEAN=["Need a Spanish interpreter for a school meeting on Thursday at 4.","Help me with a utility shutoff notice, due in 5 days.",
"Looking for Habitat for Humanity contacts to repair a porch.","Ride from the VA Clinic to home, about 12 miles.",
"Contact the school counselor about my son's missing credits.","Please call after 6 to confirm the grocery drop.",
"For Christmas we need toys for 4 children aged 3 to 9.","Request for Halloween costume donations from local stores.",
"Looking for a Notary to sign a lease, ideally this week.","Tutor needed for Calculus and Physics, 2 hours weekly.",
"Thanks for helping last month, we are doing better now.","From the Food Bank we got boxes, but we still need milk."]
PII=[("Hello, I'm Amara Nwosu and I need a ride.","Amara Nwosu"),("call me at 4 8 0 5 5 5 0 1 7 7","4 8 0 5 5 5 0 1 7 7"),
("my email: t.nguyen@gmail.com","t.nguyen@gmail.com"),("I live at 910 S College Ave Tempe AZ 85281 on the 2nd floor","910 S College Ave Tempe AZ 85281"),
("Please contact my sister Ayesha Khan for details","Ayesha Khan"),("Text 480-555-0166 or 602 555 0199","480-555-0166"),
("This is Hiroshi Tanaka writing about my mother's rent","Hiroshi Tanaka"),("Mi hija Valentina necesita clases","Valentina")]
fp=[t for t in CLEAN if D.detect_layered(t,rx)]
print("clean flagged:",len(fp),"of",len(CLEAN)); [print("  FP:",t,[t[a:b] for a,b,_ in D.detect_layered(t,rx)]) for t in fp]
ok=0
for t,g in PII:
    sp=D.detect_layered(t,rx); i=t.find(g); cov=sum(max(0,min(e,i+len(g))-max(s_,i)) for s_,e,_ in sp)/len(g)
    ok+=cov>=0.8
    if cov<0.8: print("  MISS:",t)
print("pii caught",ok,"of",len(PII))
