// ======================================
// NORESTRICTIONS AGENT v1.0
// ======================================

class Agent {

  static VERSION = "1.0";

  // فحص الصورة
  static async inspect(imageData) {
    try {
      if (!imageData) {
        throw new Error("Image is required");
      }

      const image = decodeImage(imageData);
      const result = Work.inspect(image);

      return {
        success: true,
        agent: "NoRestrictions Agent",
        version: this.VERSION,

        image: {
          format: "PNG",
          size: image.length
        },

        metadata: result.metadata,

        message: "Image inspected successfully"
      };

    } catch (error) {
      return this.error(error);
    }
  }

  // تجهيز معاينة التعديل دون تسليم الصورة المعدّلة
  static async prepareEdit(imageData, operations) {
    try {
      if (!imageData) {
        throw new Error("Image is required");
      }

      if (!Array.isArray(operations) || operations.length === 0) {
        throw new Error("No operations provided");
      }

      const image = decodeImage(imageData);

      const before = Work.inspect(image).metadata;

      const result = Work.process(
        image,
        operations
      );

      return {
        success: true,
        agent: "NoRestrictions Agent",
        version: this.VERSION,

        status: "awaiting_confirmation",

        preview: {
          before,
          after: result.metadata,
          operations
        },

        message: "Review the changes before applying them"
      };

    } catch (error) {
      return this.error(error);
    }
  }

  // تنفيذ التعديلات بعد التأكيد
  static async applyEdit(imageData, operations, confirmed) {
    try {
      if (confirmed !== true) {
        throw new Error("User confirmation is required");
      }

      if (!imageData) {
        throw new Error("Image is required");
      }

      if (!Array.isArray(operations) || operations.length === 0) {
        throw new Error("No operations provided");
      }

      const image = decodeImage(imageData);

      const result = Work.process(
        image,
        operations
      );

      return {
        success: true,
        agent: "NoRestrictions Agent",
        version: this.VERSION,

        status: "completed",

        image: encodeImage(result.image),

        format: "image/png",

        metadata: result.metadata,

        message: "Image metadata updated successfully"
      };

    } catch (error) {
      return this.error(error);
    }
  }

  // استقبال المهمة وتوجيهها
  static async run(task) {
    try {
      if (!task || typeof task !== "object") {
        throw new Error("Invalid task");
      }

      switch (task.action) {

        case "inspect":
          return await this.inspect(task.image);

        case "preview":
          return await this.prepareEdit(
            task.image,
            task.operations
          );

        case "apply":
          return await this.applyEdit(
            task.image,
            task.operations,
            task.confirmed
          );

        default:
          throw new Error("Unknown agent action");
      }

    } catch (error) {
      return this.error(error);
    }
  }

  // معالجة الأخطاء
  static error(error) {
    return {
      success: false,
      agent: "NoRestrictions Agent",
      version: this.VERSION,
      error: error.message || "Agent error"
    };
  }
}
