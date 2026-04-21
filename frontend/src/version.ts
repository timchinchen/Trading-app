// App version - kept in sync with the GitHub git tag on each commit.
//
// Versioning scheme: X.Y.Z
//   X = major (human-controlled, bumped by the user)
//   Y = minor (human-controlled, bumped by the user)
//   Z = patch (droid-controlled, incremented on every droid-authored edit)
//
// On every droid-authored change, bump Z by 1 and re-tag the commit on
// GitHub with the matching vX.Y.Z tag so this file is the single source
// of truth that stays in lockstep with the repo tags.
export const APP_VERSION = '1.0.3'
