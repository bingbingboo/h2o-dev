package water.api;

import water.api.FramesHandler.Frames;
import water.api.KeyV1.FrameKeyV1;
import water.fvec.Frame;

abstract class FramesBase<I extends Frames, S extends FramesBase<I, S>> extends Schema<I, FramesBase<I, S>> {
  // Input fields
  @API(help="Key of Frame of interest", json=false) // TODO: no validation yet, because right now fields are required if they have validation.
  public FrameKeyV1 key; // TODO: change to Frame

  @API(help="Name of column of interest", json=false) // TODO: no validation yet, because right now fields are required if they have validation.
  public String column;

  @API(help="Row offset to display", direction=API.Direction.INOUT)
  public long row_offset;

  @API(help="Number of rows to display", direction=API.Direction.INOUT)
  public int row_count;

  @API(help="Find and return compatible models?", json=false)
  public boolean find_compatible_models = false;

  // Output fields
  @API(help="Frames", direction=API.Direction.OUTPUT)
  FrameV2[] frames; // TODO: create interface or superclass (e.g., FrameBase) for FrameV2

  @API(help="Compatible models", direction=API.Direction.OUTPUT)
  ModelSchema[] compatible_models;

  @API(help="Domains", direction=API.Direction.OUTPUT)
  String[][] domain;

  // Non-version-specific filling into the impl
  @Override public I fillImpl(I f) {
    super.fillImpl(f);

    if (null != frames) {
      f.frames = new Frame[frames.length];

      int i = 0;
      for (FrameV2 frame : this.frames) { // TODO: base class for FrameV2!
        f.frames[i++] = frame._fr;
      }
    }
    return f;
  }

  // TODO: parameterize on the FrameVx Schema class
  @Override public FramesBase fillFromImpl(Frames f) {
    this.key = new FrameKeyV1(f.key);
    this.column = f.column; // NOTE: this is needed for request handling, but isn't really part of state
    this.find_compatible_models = f.find_compatible_models;

    if (null != f.frames) {
      this.frames = new FrameV2[f.frames.length];

      int i = 0;
      for (Frame frame : f.frames) {
        this.frames[i++] = new FrameV2(frame, f.offset, f.len);
      }
    }
    return this;
  }
}
