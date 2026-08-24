# Apache Commons Codec phonetic boundary handling live repository evaluation

- Recorded at: `2026-08-24T15:31:42.470505Z`
- Harness revision: `ea4c2113d55b899c9fbf5c812a4942fc0b5bb3b1`
- Target revision: `41871c2cc31ebab1865736c61026d193409b30b5`
- Outcome: `candidate_stopped`
- Public baseline -> best: `0.5` -> `0.5`
- Hidden baseline -> observed: `0.4` -> `0.4`
- Validation acceptance: `minimum_improvement`, target `1.0`, delta `0.6`
- Model: `dashscope.aliyuncs.com/qwen3-coder-plus`
- Request attempts/usage reports/tokens: `1` / `1` / `6284`
- Token-derived cost: `0.033668 CNY`
- Editable files: `src/main/java/org/apache/commons/codec/language/bm/PhoneticEngine.java`

## Keep/Reject ledger

| Trial | Status | Decision | Public metric | Reason |
| ---: | --- | --- | ---: | --- |
| 0 | baseline | keep | 0.5 | frozen baseline |
| 1 | rejected | reject |  | RuntimeError: guard command failed: {"upstream_checks_passed": false, "command": ["mvn", "-q", "-Drat.skip=true", "test"], "exit_code": 1, "duration_ms": 38578, "surefire": {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}, "stdout_tail": "[ERROR] Tests run: 4, Failures: 1, Errors: 0, Skipped: 0, Time elapsed: 0.019 s <<< FAILURE! -- in org.apache.commons.codec.language.bm.PhoneticEngineRegressionTest\n[ERROR] org.apache.commons.codec.language.bm.PhoneticEngineRegressionTest.testSolrSEPHARDIC -- Time elapsed: 0.008 s <<< FAILURE!\norg.opentest4j.AssertionFailedError: expected: <danZelo\|dandZelo\|danxelo> but was: <anZelo\|andZelo\|anxelo>\n\tat org.junit.jupiter.api.AssertionFailureBuilder.build(AssertionFailureBuilder.java:151)\n\tat org.junit.jupiter.api.AssertionFailureBuilder.buildAndThrow(AssertionFailureBuilder.java:132)\n\tat org.junit.jupiter.api.AssertEquals.failNotEqual(AssertEquals.java:197)\n\tat org.junit.jupiter.api.AssertEquals.assertEquals(AssertEquals.java:182)\n\tat org.junit.jupiter.api.AssertEquals.assertEquals(AssertEquals.java:177)\n\tat org.junit.jupiter.api.Assertions.assertEquals(Assertions.java:1141)\n\tat org.apache.commons.codec.language.bm.PhoneticEngineRegressionTest.testSolrSEPHARDIC(PhoneticEngineRegressionTest.java:258)\n\tat java.lang.reflect.Method.invoke(Method.java:498)\n\tat java.util.ArrayList.forEach(ArrayList.java:1257)\n\tat java.util.ArrayList.forEach(ArrayList.java:1257)\n\n[ERROR] Failures: \n[ERROR]   PhoneticEngineRegressionTest.testSolrSEPHARDIC:258 expected: <danZelo\|dandZelo\|danxelo> but was: <anZelo\|andZelo\|anxelo>\n[ERROR] Tests run: 1339, Failures: 1, Errors: 0, Skipped: 66\n[ERROR] Failed to execute goal org.apache.maven.plugins:maven-surefire-plugin:3.1.2:test (default-test) on project commons-codec: There are test failures.\n[ERROR] \n[ERROR] Please refer to {temp}\\rp-codec-mk5ghi89\\repo\\target\\surefire-reports for the individual test results.\n[ERROR] Please refer to dump files (if any exist) [date].dump, [date]-jvmRun[N].dump and [date].dumpstream.\n[ERROR] -> [Help 1]\n[ERROR] \n[ERROR] To see the full stack trace of the errors, re-run Maven with the -e switch.\n[ERROR] Re-run Maven using the -X switch to enable full debug logging.\n[ERROR] \n[ERROR] For more information about the errors and possible solutions, please read the following articles:\n[ERROR] [Help 1] http://cwiki.apache.org/confluence/display/MAVEN/MojoFailureException\n", "stderr_tail": ""}  |
| 2 | stopped | reject |  | live request cap reached (1) |

## Evidence boundary

This is one bounded module repair in a pinned external repository, not a full-project benchmark. The evaluator subprocess receives a stripped environment but runs locally rather than in a network-isolated container. Hidden validation is withheld from the proposer context. Cost is derived from provider-reported tokens and the cited public rate, not from a billing-console receipt.
