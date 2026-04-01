/// <reference types="@raycast/api">

/* 🚧 🚧 🚧
 * This file is auto-generated from the extension's manifest.
 * Do not modify manually. Instead, update the `package.json` file.
 * 🚧 🚧 🚧 */

/* eslint-disable @typescript-eslint/ban-types */

type ExtensionPreferences = {}

/** Preferences accessible in all the extension's commands */
declare type Preferences = ExtensionPreferences

declare namespace Preferences {
  /** Preferences accessible in the `list-deadlines` command */
  export type ListDeadlines = ExtensionPreferences & {}
  /** Preferences accessible in the `create-deadline` command */
  export type CreateDeadline = ExtensionPreferences & {}
}

declare namespace Arguments {
  /** Arguments passed to the `list-deadlines` command */
  export type ListDeadlines = {}
  /** Arguments passed to the `create-deadline` command */
  export type CreateDeadline = {}
}

