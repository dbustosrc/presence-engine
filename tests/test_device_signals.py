from copy import deepcopy
import unittest

from presence_engine.adapters import AdapterEnvelope
from presence_engine.configuration import ConfigurationError, parse_configuration
from presence_engine.runtime import PresenceRuntime
from helpers import at


def configuration(limit=3, seconds=20):
    return {"schema_version":1, "areas":{}, "cameras":{}, "sources":[{
        "source_id":"distance_a", "adapter":"bermuda_signal", "entity_ids":["sensor.distance_a"],
        "identity":"person_a", "options":{"device_id":"phone_a", "receiver_id":"receiver_a",
            "metric":"distance", "history_limit":limit, "history_seconds":seconds}}]}


class DeviceSignalTests(unittest.TestCase):
    def setUp(self):
        self.second=0
        self.config=configuration()
        self.runtime=PresenceRuntime(parse_configuration(self.config),now=lambda:at(self.second))

    def deliver(self,state,second,unit="m",observed=None,channel="sensor.distance_a",extra=None):
        self.second=second
        return self.runtime.process(AdapterEnvelope("state",channel,
            {"state":str(state), "attributes":{"unit_of_measurement":unit, **(extra or {})}},
            at(second if observed is None else observed),at(second)))

    def test_signals_never_create_or_revise_presence(self):
        initial=self.runtime.snapshot
        for state,second in ((2,1),(1.5,2),(0,3),("unavailable",4)):
            update=self.deliver(state,second)
            self.assertEqual(update.snapshot,initial)
            self.assertFalse(update.changed)
            self.assertEqual(update.detections,())
            self.assertEqual(update.snapshot.devices,())
        history=self.runtime.signal_history_payload(include_samples=True)[0]
        self.assertEqual(history["status"],"unavailable")
        self.assertIsNone(history["latest_value"])

    def test_units_missing_values_and_unavailable_are_not_zero(self):
        for state,unit,status in ((0,"mm","valid"),(-1,"mm","invalid_value"),("nan","m","invalid_value"),
                                  ("inf","m","invalid_value"),(3,"dBm","invalid_unit"),
                                  (3,"","invalid_unit"),("unknown","m","unknown"),("unavailable","m","unavailable")):
            self.deliver(state,self.second+1,unit)
            actual=self.runtime.signal_history_payload()[0]
            self.assertEqual(actual["status"],status)
            self.assertEqual(actual["unit"],unit)
            self.assertEqual(actual["latest_value"],0 if status=="valid" else None)

    def test_clock_order_duplicates_and_attributes_do_not_renew_samples(self):
        self.deliver(2,1)
        self.deliver(3,2,observed=.5)
        self.deliver(2,3,extra={"friendly_name":"Renamed"})
        actual=self.runtime.signal_history_payload()[0]
        self.assertEqual(actual["sample_count"],1)
        self.assertEqual(actual["observed_at"],at(1).isoformat())
        self.deliver(2,4,unit="cm")
        self.assertEqual(self.runtime.signal_history_payload()[0]["sample_count"],2)
        self.deliver(5,5,observed=6)
        self.assertEqual(self.runtime.failures[0].error_type,"ValueError")

    def test_retention_restart_and_corrupt_records_do_not_refresh_clocks(self):
        for second in range(1,6):
            self.deliver(second,second)
        saved=self.runtime.export_state()
        self.assertEqual(len(saved["device_signals"]),3)
        self.assertTrue(self.runtime.signal_history_payload()[0]["truncated"])
        saved["device_signals"].append({"corrupt":True})
        self.runtime=PresenceRuntime(parse_configuration(self.config),now=lambda:at(self.second))
        self.runtime.restore_state(saved)
        self.assertEqual(self.runtime.signal_history_payload()[0]["observed_at"],at(5).isoformat())
        self.second=25
        self.assertEqual(self.runtime.signal_history_payload()[0]["sample_count"],0)
        saved=self.runtime.export_state()
        self.runtime=PresenceRuntime(parse_configuration(self.config),now=lambda:at(self.second))
        self.runtime.restore_state(saved)
        self.deliver(5,26,extra={"friendly_name":"Refresh"})
        self.assertEqual(self.runtime.signal_history_payload()[0]["status"],"no_recent_samples")

    def test_receivers_share_global_budget_but_not_samples(self):
        raw=configuration(limit=32)
        second=deepcopy(raw["sources"][0]); second.update(source_id="distance_b",entity_ids=["sensor.distance_b"])
        second["options"]["receiver_id"]="receiver_b"
        raw["sources"].append(second)
        self.runtime=PresenceRuntime(parse_configuration(raw),now=lambda:at(self.second),max_records=3)
        for index in range(1,8):
            self.deliver(index,index,channel="sensor.distance_a" if index%2 else "sensor.distance_b")
        self.assertEqual(len(self.runtime.export_state()["device_signals"]),3)
        self.assertEqual({r["receiver_id"] for r in self.runtime.signal_history_payload()}, {"receiver_a","receiver_b"})
        self.second=8
        self.runtime.mark_channel_unavailable(("distance_a",))
        self.assertEqual(self.runtime.signal_history_payload()[0]["status"],"unavailable")
        self.assertFalse(self.runtime.snapshot.coverage_degraded)

    def test_invalid_configuration_is_rejected(self):
        for key,value in (("device_id",""),("receiver_id",None),("metric","movement"),
                          ("history_seconds",float("inf")),("history_limit",True),("history_limit",257)):
            raw=configuration(); raw["sources"][0]["options"][key]=value
            with self.assertRaises(ConfigurationError):
                parse_configuration(raw)
        raw=configuration(); raw["sources"][0]["availability_role"]="coverage"
        with self.assertRaises(ConfigurationError):
            parse_configuration(raw)


if __name__=="__main__":
    unittest.main()
