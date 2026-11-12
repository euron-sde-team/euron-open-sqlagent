# 0009: One package, three roles

**Status:** accepted

The API, the question worker and the scheduler share models, services and settings. One
package and one image run them as `sqlagent serve`, `sqlagent worker` and
`sqlagent scheduler`, so a release is one build and the roles never drift apart.
